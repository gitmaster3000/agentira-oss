"""Context assembly — one path for building the dispatch prompt (AP-181).

Owns the "what history does the agent see this turn?" decision: native resume
short-circuit, token-budgeted rebuild, and rolling-summary compaction. Kept out
of the 4k-line services.py on purpose (a cohesive concern). The conversation's
rolling_summary is written at turn completion by services; here it's read-only.

Stateless module of functions over its own session.
"""

from __future__ import annotations

from backend.forge.models import AgentMessage, MessageRole, Run, Conversation

_TOOL_ENTRY_TRUNCATE = 4096   # ~4KB per tool entry
# Max rows fetched per context rebuild. The token-budget loop is the real
# limiter; this only stops the query from materializing an unbounded history.
_CONTEXT_ROW_CAP = 1000
# Per-field fetch cap for USER/ASSISTANT content, applied SQL-side. A single
# stored message can be megabytes (Conductor planning prompts with full board
# dumps — see AP-205); the row cap alone doesn't bound memory when individual
# rows are that big (prod OOM #3, 2026-07-07: newest 1000 rows of the
# Conductor's chat:default scope totalled 884MB). ~100K chars ≈ 25K tokens,
# already half the default budget — nothing legitimate needs more per row.
_CONTENT_FETCH_CAP = 100_000
# Token budget for a rebuilt history preamble (gateway runtimes / when a
# native session is lost). ~50K tokens keeps real continuity while staying
# well inside the model context. One budgeted path for every scope — replaces
# the old 200KB task byte-cap AND the separate 20-message chat cap.
DEFAULT_CONTEXT_TOKENS = 50_000


def _estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) — good enough to budget a history
    preamble without pulling in a tokenizer dependency."""
    return (len(text) + 3) // 4


def _render_history_row(m: "AgentMessage") -> str | None:
    """Format a single AgentMessage row for the rebuilt history transcript.

    Includes TOOL events alongside USER/ASSISTANT so the agent has
    visibility into prior tool_use/tool_result steps when native session
    resume is unavailable.
    """
    if m.role == MessageRole.USER:
        return f"User: {m.content}"
    if m.role == MessageRole.ASSISTANT:
        return f"Assistant: {m.content}"
    if m.role == MessageRole.TOOL:
        if m.tool_name:
            inp = (m.tool_input or "").strip()
            if len(inp) > _TOOL_ENTRY_TRUNCATE:
                inp = inp[:_TOOL_ENTRY_TRUNCATE] + "…"
            return f"Tool: Used {m.tool_name}({inp})"
        out = (m.tool_output if m.tool_output is not None else m.content) or ""
        out = out.strip()
        if len(out) > _TOOL_ENTRY_TRUNCATE:
            out = out[:_TOOL_ENTRY_TRUNCATE] + "…"
        return f"Tool: → {out}"
    return None


def assemble_context(*, agent_id: str, scope_key: str, current: str,
                     token_budget: int = DEFAULT_CONTEXT_TOKENS,
                     native_resume_available: bool = False) -> str:
    """Build the dispatch prompt — one path for every runtime/scope.

    1. If the runtime carries history natively (a live `--resume` session),
       return the prompt unchanged. Native resume is the optimization, not a
       separate semantic — so when it's unavailable (gateway runtime, or a
       lost claude session) we always fall back to the rebuild below.
    2. Rebuild a transcript newest→oldest against a TOKEN budget, always
       including TOOL events. When the budget is exceeded, older turns are
       represented by the conversation's rolling summary (updated at turn
       completion) instead of being silently dropped.
    """
    if native_resume_available:
        return current

    # Lazy import keeps this module import-light and routes DB access through
    # the same session factory the rest of forge uses (one test patch point).
    from backend.forge.services import _session

    roles = [MessageRole.USER, MessageRole.ASSISTANT, MessageRole.TOOL]
    rendered_rev: list[str] = []
    used = 0
    summary: str | None = None
    from sqlalchemy import func

    with _session() as db:
        # Fetch only the fields the renderer reads, truncated in SQL. Loading
        # full AgentMessage rows pulls every blob column into memory; the
        # renderer truncates tool entries to _TOOL_ENTRY_TRUNCATE anyway, so
        # fetching more than that (+1 so the renderer still detects overflow
        # and appends its ellipsis) is pure waste — and on blob-heavy scopes
        # it was gigabytes of waste per dispatch.
        tool_cap = _TOOL_ENTRY_TRUNCATE + 1
        q = (db.query(
                AgentMessage.role,
                AgentMessage.tool_name,
                func.substr(AgentMessage.content, 1,
                            _CONTENT_FETCH_CAP).label("content"),
                func.substr(AgentMessage.tool_input, 1,
                            tool_cap).label("tool_input"),
                func.substr(AgentMessage.tool_output, 1,
                            tool_cap).label("tool_output"))
               .filter(AgentMessage.agent_id == agent_id,
                       AgentMessage.role.in_(roles)))
        # Scope filter: only this conversation. Empty scope_key (legacy rows)
        # matches nothing, which is the safe default.
        if scope_key:
            q = q.filter(AgentMessage.scope_key == scope_key)
        # Walk newest→oldest, accumulate until the token budget, then reverse
        # to chronological order. Hard row cap: without it, .all() materializes
        # the scope's ENTIRE history (tool blobs included) before the budget
        # loop runs — on long-lived threads that was multi-GB per dispatch and
        # the prod OOM crash driver (2026-07-07). The budget loop breaks long
        # before this cap on any realistic token_budget.
        for m in (q.order_by(AgentMessage.created_at.desc(),
                             AgentMessage.id.desc())
                    .limit(_CONTEXT_ROW_CAP).all()):
            line = _render_history_row(m)
            if line is None:
                continue
            cost = _estimate_tokens(line) + 1
            if used + cost > token_budget and rendered_rev:
                break  # older turns beyond the budget → carried by the summary
            rendered_rev.append(line)
            used += cost
        rendered = list(reversed(rendered_rev))

        # Carry-over: the conversation's rolling summary (kept fresh at turn
        # completion), falling back to the latest finished run's summary.
        conv = (db.query(Conversation)
                  .filter_by(agent_id=agent_id, scope_key=scope_key).first())
        if conv and conv.rolling_summary:
            summary = conv.rolling_summary.strip() or None
        if summary is None and scope_key and scope_key.startswith("task:"):
            task_id = scope_key[len("task:"):]
            latest_run = (db.query(Run)
                          .filter(Run.agent_id == agent_id,
                                  Run.task_id == task_id,
                                  Run.summary.isnot(None))
                          .order_by(Run.finished_at.desc().nullslast(),
                                    Run.created_at.desc())
                          .first())
            if latest_run and latest_run.summary:
                summary = latest_run.summary.strip() or None

    if not rendered and not summary:
        return current
    parts = ["<conversation history>"]
    if summary:
        parts.append(f"Earlier context (summary): {summary}")
    parts.extend(rendered)
    parts.append("</conversation history>\n")
    parts.append(current)
    return "\n".join(parts)
