"""AgentIRA daemon — runtime host.

Detects local CLI runtimes, registers them with the server, sends heartbeats,
and listens on a WebSocket for `task_available` push frames. Task execution
is dispatched per-frame; there is no per-bot polling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import signal
import threading
import time
import traceback

from agentira_cli.runtimes.registry import detect_all, get_runtime_cls
from agentira_cli.state.config import DaemonConfig
from agentira_cli.state.paths import DAEMON_ID_FILE, ensure_home
from agentira_cli.transport.rest import AgentiraClient

logger = logging.getLogger("agentira.daemon")


def _ensure_worktree(*, source: str, target: str, branch: str) -> None:
    """Create a git worktree at `target` off `source` on branch `branch`.

    Idempotent: if `target/.git` already exists, no-op.
    Runs on the daemon host where both paths are real. Backend can't do
    this because the user's repo (`source`) lives outside the docker
    container.

    Quiet about failure modes — log warnings, never crash the dispatch.
    """
    import os
    import subprocess
    if not source or not target:
        return
    if not os.path.isdir(source):
        return
    if os.path.exists(os.path.join(target, ".git")):
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    # `-B` so re-creating after a worktree prune doesn't trip on the
    # branch already existing.
    subprocess.run(
        ["git", "-C", source, "worktree", "add", "-B", branch, target],
        check=True, timeout=60,
    )


def _load_or_create_daemon_id() -> str:
    ensure_home()
    if DAEMON_ID_FILE.exists():
        return DAEMON_ID_FILE.read_text().strip()
    import uuid
    daemon_id = str(uuid.uuid4())
    DAEMON_ID_FILE.write_text(daemon_id)
    return daemon_id


class AgentiraDaemon:
    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self._running = False
        self._wake_event = threading.Event()
        self._task_queue: queue.Queue = queue.Queue()
        self._active = threading.Semaphore(3)
        self.client = AgentiraClient(base_url=config.api_url, api_key=config.api_key)
        self._daemon_id = _load_or_create_daemon_id()
        self._registered: list[dict] = []
        # Track in-flight executions so a cancel frame can kill the right
        # subprocess. Keyed by trace_id (the dispatch primary key); we also
        # keep a parallel run_id → trace_id map so backend cancels by
        # run_id resolve correctly. CLI runs register their proc here;
        # http_gateway runs register None (cancel is best-effort: nothing
        # to kill mid-request, the run completes naturally).
        self._inflight: dict[str, dict] = {}
        self._run_to_trace: dict[str, str] = {}
        # ADR 009 / B6: scope_key → trace_id so a stop frame can target the
        # live turn for a scope (chats have no run_id to key on).
        self._scope_to_trace: dict[str, str] = {}
        self._inflight_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        self._install_signal_handlers()

        self._registered = self._register_runtimes()

        # ADR 009 / B3: reap orphaned turns a prior daemon left running
        # (start_new_session keeps claude alive across our death). A fresh
        # daemon owns no in-memory inflight, so any on-disk record is an
        # orphan — kill its process group, then clear the record.
        try:
            from agentira_cli.daemon import inflight as _inflight_reg
            _inflight_reg.reap_orphans(daemon_id=self._daemon_id)
        except Exception as exc:  # noqa: BLE001 — never block startup
            logger.warning("inflight reaper failed: %s", exc)

        from agentira_cli.daemon.workdir import WorkdirGC
        self._gc = WorkdirGC()
        self._gc.start()

        if self._registered:
            from agentira_cli.daemon.ws_client import DaemonWsClient
            runtime_ids = [r.get("id", "") for r in self._registered if r.get("id")]
            self._ws = DaemonWsClient(
                api_url=self.config.api_url,
                api_key=self.config.api_key,
                daemon_id=self._daemon_id,
                runtime_ids=runtime_ids,
                wake_event=self._wake_event,
                task_queue=self._task_queue,
            )
            self._ws.start()

        logger.info(
            "Daemon started — daemon_id=%s runtimes=%d dry_run=%s",
            self._daemon_id[:8], len(self._registered), self.config.dry_run,
        )

        # Heartbeat loop
        interval = max(5, int(self.config.heartbeat_interval))
        while self._running:
            self._wake_event.wait(timeout=interval)
            if not self._running:
                break
            self._wake_event.clear()
            self._heartbeat()
            # Drain pending tasks from the WS queue. Frames carry a
            # `type` so we can route triggers and cancels through the
            # same channel without an extra queue.
            while True:
                try:
                    frame = self._task_queue.get_nowait()
                except queue.Empty:
                    break
                ftype = frame.get("type", "trigger")
                if ftype == "cancel":
                    self._cancel(frame)
                elif ftype in ("pause", "resume"):
                    self._signal_proc(frame, ftype)
                else:
                    self._dispatch_task(frame)

        self._shutdown()

    def _shutdown(self) -> None:
        self._running = False
        logger.info("Daemon stopped.")

    # ── Signal handling ───────────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:  # noqa: ARG002
        logger.info("Signal %d — stopping.", signum)
        self._running = False
        self._wake_event.set()

    # ── Runtime registration / heartbeat ──────────────────────────────────

    def _register_runtimes(self) -> list[dict]:
        detected = detect_all()
        if not detected:
            logger.info("No runtimes detected on PATH.")
            return []

        # If OpenClaw is detected, idempotently add the generic
        # `agentira-runner` agent to ~/.openclaw/openclaw.json. Agentira
        # routes ALL its OpenClaw chats through this runner so OpenClaw's
        # per-agent bootstrap/persona doesn't fight our system_prompt.
        # See agentira_cli/runtimes/openclaw.py::ensure_runner_agent.
        if any(d.provider == "openclaw" for d in detected):
            try:
                from agentira_cli.runtimes.openclaw import ensure_runner_agent
                ensure_runner_agent()
            except Exception as exc:
                logger.warning("ensure_runner_agent failed: %s", exc)

        from agentira_cli.daemon.host_tools import discover_for
        runtimes = [
            {
                "provider": d.provider,
                "binary_path": d.binary_path,
                "version": d.version,
                "capabilities": d.capabilities,
                "models": d.models,
                "gateway_url": d.gateway_url,
                "gateway_token": d.gateway_token,
                "host_tools": discover_for(d.provider),
            }
            for d in detected
        ]
        logger.info("Detected runtimes: %s", ", ".join(d.provider for d in detected))
        try:
            result = self.client.register_runtimes(
                daemon_id=self._daemon_id,
                device_name=self.config.device_name,
                runtimes=runtimes,
            )
            registered = result.get("registered", [])
            logger.info("Registered %d runtime(s) with server.", len(registered))
            return registered
        except Exception as exc:
            logger.warning("Runtime registration failed: %s", exc)
            return []

    async def _post_setup_failure(self, *, trace_id: str, run_id: str,
                                  agent_id: str, reason: str) -> None:
        """Report a pre-spawn failure back to the backend so the user sees
        what broke instead of the trigger silently disappearing."""
        try:
            self.client.post_trigger_complete(
                agent_id,
                daemon_id=self._daemon_id,
                trace_id=trace_id,
                run_id=run_id or "",
                success=False,
                input_tokens=0,
                output_tokens=0,
                error=f"Setup failed before runtime spawn: {reason}",
            )
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("post_trigger_complete (setup failure) failed: %s", exc)

    def _dispatch_task(self, frame: dict) -> None:
        """Spawn a daemon thread to execute the task described by frame."""
        if not self._active.acquire(blocking=False):
            logger.warning("Max concurrent tasks reached — dropping frame run=%s", frame.get("run_id", ""))
            return
        def _run():
            try:
                asyncio.run(self._execute(frame))
            finally:
                self._active.release()
        threading.Thread(target=_run, daemon=True).start()

    async def _execute(self, frame: dict) -> None:
        """Execute a single trigger frame dispatched from the WS hub.

        One path for chat, run_step, and any future trigger kinds. The daemon
        does not branch on `kind` — that's a server-side audit field. We only
        route on runtime capability (http_gateway vs stream-json subprocess).
        """
        from agentira_cli.daemon.executor import run_cli_stream, run_gateway
        from agentira_cli.daemon.materializer import (
            materialize, compose_system_prompt, ensure_memory_dirs,
        )

        trace_id = frame.get("trace_id", "")
        run_id = frame.get("run_id", "") or ""
        agent_id = frame.get("agent_id", "")
        task_id = frame.get("env_extra", {}).get("AGENTIRA_TASK_ID", "") if isinstance(frame.get("env_extra"), dict) else ""
        prompt = frame.get("prompt", "")
        provider = frame.get("provider", "")
        kind = frame.get("kind", "chat")
        # ADR 009 / B1: the conversation scope rides the frame. It keys the
        # durable inflight registry (one live turn per scope) and lets a
        # task-scoped CHAT (no run_id, so no AGENTIRA_TASK_ID) recover its
        # task_id — without this the materializer fell back to a divergent
        # "chat" workdir, splitting claude --resume across cwds (ADR 009).
        scope_key = frame.get("scope_key", "") or ""
        if not task_id and scope_key.startswith("task:"):
            task_id = scope_key.split(":", 1)[1]

        # Run-context bundle (Phase C dispatched these; empty for free-floating chat).
        # repo_path is a path TEMPLATE from backend (may contain `~`).
        # Daemon expands against the host's HOME — backend can't because
        # it runs as root inside docker.
        import os as _os
        repo_path = _os.path.expanduser(frame.get("repo_path", "") or "")
        # Worktree provisioning info: agent's cwd (repo_path above) is
        # where claude will run, but the WORK has to come from somewhere.
        # `worktree_source_path` is the user's local git repo on the
        # host. If present, we `git worktree add` from it into repo_path
        # so the agent has a real working tree to edit + commit in.
        worktree_source_path = _os.path.expanduser(
            frame.get("worktree_source_path", "") or ""
        )
        worktree_source_url = frame.get("worktree_source_url", "") or ""
        worktree_branch = frame.get("worktree_branch", "") or ""
        conventions_md = frame.get("conventions_md", "") or ""
        mcp_config_json = frame.get("mcp_config_json", "") or ""
        mcp_strict = bool(frame.get("mcp_strict", False))
        resume_session_id = frame.get("resume_session_id", "") or ""
        # Per-run log directory the backend stamped on the Run row.
        # Daemon tees stdout / stderr into log files here and writes
        # meta.json at end. Expanduser on the daemon host (the path
        # was intentionally NOT expanded on the backend side, where ~
        # would resolve to /root inside the container).
        log_dir = _os.path.expanduser(frame.get("log_dir", "") or "")
        stdout_log_path = ""
        stderr_log_path = ""
        if log_dir:
            try:
                _os.makedirs(log_dir, exist_ok=True)
                stdout_log_path = _os.path.join(log_dir, "stdout.log")
                stderr_log_path = _os.path.join(log_dir, "stderr.log")
                logger.info("per-run logs: %s", log_dir)
            except OSError as exc:
                logger.warning("log_dir create failed (%s): %s", log_dir, exc)
                log_dir = ""

        # Daemon owns filesystem provisioning. Ensure the agent's home
        # exists (with subdirs); if a worktree source is provided, ensure
        # the worktree at repo_path is created off the source.
        if repo_path:
            try:
                _os.makedirs(repo_path, exist_ok=True)
                for sub in ("repos", "memory", "notes", ".agentira"):
                    sub_path = _os.path.join(
                        # If repo_path is a worktree subdir, its parent's parent
                        # is the home; we ensure home subdirs there. Otherwise
                        # repo_path IS the home — same operation.
                        repo_path if "/repos/" not in repo_path
                        else _os.path.dirname(_os.path.dirname(repo_path)),
                        sub,
                    )
                    _os.makedirs(sub_path, exist_ok=True)
                if worktree_source_path and worktree_branch:
                    await asyncio.to_thread(
                        _ensure_worktree,
                        source=worktree_source_path,
                        target=repo_path,
                        branch=worktree_branch,
                    )
            except Exception as exc:  # noqa: BLE001 — log + continue
                logger.warning("worktree provisioning failed trace=%s: %s", trace_id, exc)
        env_extra = frame.get("env_extra", {}) or {}
        if not isinstance(env_extra, dict):
            env_extra = {}

        runtime_cls = get_runtime_cls(provider)
        if runtime_cls is None:
            logger.warning("Unknown provider '%s' trace=%s", provider, trace_id)
            return

        runtime_info = next(
            (r for r in self._registered if r.get("provider") == provider), {}
        )
        capabilities = runtime_info.get("capabilities", [])
        binary_path = runtime_info.get("binary_path", "")
        gateway_url = frame.get("gateway_url") or runtime_info.get("gateway_url", "")
        gateway_token = frame.get("gateway_token") or runtime_info.get("gateway_token", "")
        model = frame.get("model", runtime_info.get("models", [""])[0] if runtime_info.get("models") else "")
        agent_system_prompt = frame.get("system_prompt", "")
        agent_name = frame.get("agent_name", "")

        # Decode AP-76 user-context bundle if present. Frontend ships it
        # via env_extra to avoid a new WS-frame field.
        user_context: dict = {}
        uc_raw = env_extra.get("AGENTIRA_USER_CONTEXT_JSON", "")
        if uc_raw:
            try:
                import json as _json
                parsed = _json.loads(uc_raw)
                if isinstance(parsed, dict):
                    user_context = parsed
            except Exception as exc:
                logger.debug("invalid user_context: %s", exc)

        logger.info(
            "execute trigger trace=%s kind=%s agent=%s run=%s provider=%s",
            trace_id, kind, agent_id, run_id or "-", provider,
        )

        # Materialize the run env when we have somewhere to put it:
        # - Task runs (run_id + task_id) → per-task workdir under ~/.agentira/.
        # - Chat with a project (repo_path resolved from user_context) → write
        #   CONVENTIONS.md + courtesy symlinks straight into the repo.
        # - Free-form chat with no project → skip; runtime stays in daemon cwd.
        #
        # Each filesystem step runs through asyncio.to_thread with a hard
        # timeout so a stuck FS call (NFS, hung git, slow disk) fails the
        # trigger with an actionable error instead of vanishing into a
        # silent never-returning subprocess spawn.
        cwd_path = None
        materialize_reason = ""  # surfaced in diagnostics for run debugging
        try:
            if run_id and task_id:
                logger.info("step=materialize trace=%s (task run)", trace_id)
                cwd_path, _, materialize_reason = await asyncio.wait_for(
                    asyncio.to_thread(
                        materialize,
                        workspace_id=agent_id,
                        task_id=task_id,
                        repo_path=repo_path,
                        conventions_md=conventions_md,
                    ),
                    timeout=30.0,
                )
            elif repo_path:
                logger.info("step=materialize trace=%s (chat in project)", trace_id)
                # Chat in a project: don't allocate a workdir, just resolve
                # the repo path so the runtime cwd is right. Materialize
                # conventions there too — repo-local, idempotent, safe.
                # ADR 009: use the real task_id (derived from scope_key above)
                # so a task chat shares the run's workdir on the scratch-
                # fallback path; only a task-less project chat uses "chat".
                cwd_path, _, materialize_reason = await asyncio.wait_for(
                    asyncio.to_thread(
                        materialize,
                        workspace_id=agent_id,
                        task_id=task_id or "chat",
                        repo_path=repo_path,
                        conventions_md=conventions_md,
                    ),
                    timeout=30.0,
                )
            logger.info("step=ensure_memory_dirs trace=%s", trace_id)
            await asyncio.wait_for(
                asyncio.to_thread(ensure_memory_dirs, mcp_config_json),
                timeout=10.0,
            )
        except asyncio.TimeoutError:
            logger.exception("setup timed out trace=%s", trace_id)
            await self._post_setup_failure(
                trace_id=trace_id, run_id=run_id, agent_id=agent_id,
                reason="filesystem setup timed out (materialize/memory dirs > 30s)",
            )
            return
        except Exception as exc:
            logger.exception("setup crashed trace=%s: %s", trace_id, exc)
            await self._post_setup_failure(
                trace_id=trace_id, run_id=run_id, agent_id=agent_id,
                reason=f"setup error: {exc!r}",
            )
            return

        have_memory = "memory" in (mcp_config_json or "")  # cheap probe

        # Compose the system prompt: user-context preamble + conventions +
        # memory addenda + persona, in that order.
        logger.info("step=compose_system_prompt trace=%s", trace_id)
        system_prompt = compose_system_prompt(
            agent_system_prompt,
            have_conventions=bool(cwd_path and conventions_md),
            have_memory=have_memory,
            user_context=user_context or None,
        )
        logger.info(
            "step=spawning trace=%s cwd=%s mcp_strict=%s resume=%s",
            trace_id, cwd_path or "-", mcp_strict, bool(resume_session_id),
        )

        # Register in-flight bookkeeping so a cancel frame can find us.
        with self._inflight_lock:
            self._inflight[trace_id] = {"proc": None, "cancelled": False,
                                        "scope_key": scope_key, "run_id": run_id}
            if run_id:
                self._run_to_trace[run_id] = trace_id
            if scope_key:
                self._scope_to_trace[scope_key] = trace_id

        def on_proc(proc):
            # P1: close the race between dispatch and a cancel/pause frame
            # that arrived in the tiny window before the subprocess was
            # bound. If the user already asked to stop, kill immediately —
            # otherwise the subprocess would run unattended.
            stop_now = False
            kind = ""
            with self._inflight_lock:
                entry = self._inflight.get(trace_id)
                if entry is not None:
                    entry["proc"] = proc
                    if entry.get("cancelled"):
                        stop_now, kind = True, "cancel"
                    elif entry.get("paused"):
                        stop_now, kind = True, "pause"
            if stop_now and proc is not None:
                try:
                    # P5: group-kill so a fast-spawning child of claude
                    # (rare in the bind window, but possible) doesn't
                    # outlive its parent.
                    self._signal_group(proc, signal.SIGTERM)
                    logger.info("on_proc kill-on-bind trace=%s kind=%s pid=%s",
                                trace_id, kind, proc.pid)
                    self._sigkill_watchdog(trace_id, proc)
                except (ProcessLookupError, Exception) as exc:
                    logger.debug("on_proc kill ignored: %s", exc)
            elif proc is not None and scope_key:
                # ADR 009 / B2: now that we have a pid, persist the live
                # turn so a stop (even after a daemon/backend restart) can
                # find and kill it, and so the next startup can reap it if
                # we die. Best-effort — never break the dispatch.
                try:
                    from agentira_cli.daemon import inflight as _inflight_reg
                    _inflight_reg.record(
                        scope_key=scope_key, trace_id=trace_id,
                        run_id=run_id, pid=proc.pid,
                        daemon_id=self._daemon_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug("inflight record skipped trace=%s: %s",
                                 trace_id, exc)

        async def on_event(evts: list) -> None:
            try:
                self.client.post_trigger_events(
                    agent_id,
                    daemon_id=self._daemon_id,
                    trace_id=trace_id,
                    run_id=run_id,
                    events=list(evts),
                )
            except Exception as exc:
                logger.warning("post_trigger_events failed trace=%s: %s", trace_id, exc)

        success = False
        error = ""
        input_tokens = 0
        output_tokens = 0
        session_lost = False  # AP-133: flipped when we retry after --resume miss
        try:
            if "http_gateway" in capabilities:
                # AP-103: OpenClaw's chat-completions endpoint takes no
                # per-call MCP config, so register this agent's MCP
                # servers into OpenClaw's config immediately before the
                # dispatch. The runner picks up THIS agent's token +
                # memory path for the turn it's about to serve.
                if provider == "openclaw" and mcp_config_json:
                    try:
                        import json as _json
                        from agentira_cli.runtimes.openclaw import register_agentira_mcps
                        reg = register_agentira_mcps(_json.loads(mcp_config_json))
                        if reg["failed"]:
                            logger.warning("MCP register (openclaw) partial: %s", reg["failed"])
                    except Exception as exc:
                        logger.warning("MCP register (openclaw) failed trace=%s: %s",
                                       trace_id, exc)
                result = await run_gateway(
                    gateway_url, gateway_token, agent_name, prompt,
                    model=model, system_prompt=system_prompt, on_event=on_event,
                    provider=provider,
                )
            else:
                result = await run_cli_stream(
                    runtime_cls, binary_path, prompt,
                    model=model, system_prompt=system_prompt, on_event=on_event,
                    on_proc=on_proc,
                    workdir=str(cwd_path) if cwd_path else None,
                    mcp_config_json=mcp_config_json or None,
                    mcp_strict=mcp_strict,
                    resume_session_id=resume_session_id,
                    env_extra=env_extra,
                    stdout_log_path=stdout_log_path or None,
                    stderr_log_path=stderr_log_path or None,
                )
                # AP-133: graceful recovery when the stamped session_id
                # isn't on disk anymore (path mismatch, daemon restart
                # that wiped ~/.claude, cross-machine resume). Detect the
                # claude-code signature, retry once WITHOUT --resume, and
                # tell the backend to clear the stale id from the scope.
                session_lost = bool(
                    resume_session_id
                    and not result.success
                    and "No conversation found with session ID"
                        in (result.error or "")
                )
                if session_lost:
                    logger.warning(
                        "session_not_found trace=%s — claude couldn't find "
                        "session %s. Retrying without --resume; conversation "
                        "history will be rebuilt from AgentMessage on the "
                        "next chat turn.",
                        trace_id, resume_session_id[:8])
                    result = await run_cli_stream(
                        runtime_cls, binary_path, prompt,
                        model=model, system_prompt=system_prompt,
                        on_event=on_event, on_proc=on_proc,
                        workdir=str(cwd_path) if cwd_path else None,
                        mcp_config_json=mcp_config_json or None,
                        mcp_strict=mcp_strict,
                        resume_session_id="",  # fresh
                        env_extra=env_extra,
                        stdout_log_path=stdout_log_path or None,
                        stderr_log_path=stderr_log_path or None,
                    )
            success = result.success
            error = result.error
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
            session_id = getattr(result, 'session_id', '') or ''
        except Exception as exc:
            error = str(exc)
            session_id = ''
            logger.exception("trigger execution failed trace=%s", trace_id)

        # If a cancel hit us mid-flight, override success/error so the
        # backend marks the run cancelled instead of just "failed".
        with self._inflight_lock:
            entry = self._inflight.pop(trace_id, None)
            if run_id:
                self._run_to_trace.pop(run_id, None)
            if scope_key and self._scope_to_trace.get(scope_key) == trace_id:
                self._scope_to_trace.pop(scope_key, None)
        # ADR 009 / B2: drop the durable record (only if it's still ours —
        # clear() guards against clobbering a newer turn that took the scope).
        if scope_key:
            try:
                from agentira_cli.daemon import inflight as _inflight_reg
                _inflight_reg.clear(scope_key=scope_key, trace_id=trace_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("inflight clear skipped trace=%s: %s", trace_id, exc)
        if entry and entry.get("cancelled"):
            success = False
            error = "Cancelled by user."
            # P1: post a dedicated cancelled completion so the backend
            # flips the run to CANCELLED (not FAILED) and skips the
            # admin "execution failed" notification. Without this the
            # cancel was indistinguishable from a crash.
            try:
                resp = self.client.post_trigger_complete(
                    agent_id,
                    daemon_id=self._daemon_id,
                    trace_id=trace_id,
                    run_id=run_id,
                    success=False,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error=error,
                    session_id=session_id,
                    workdir=str(cwd_path) if cwd_path else "",
                    cancelled=True,
                    materialize_reason=materialize_reason,
                )
            except Exception as exc:
                logger.warning("cancelled-complete post failed trace=%s: %s",
                                trace_id, exc)
                resp = {}
            if log_dir:
                self._write_run_meta(log_dir, {
                    "run_id": run_id, "trace_id": trace_id, "agent_id": agent_id,
                    "cwd": str(cwd_path) if cwd_path else "",
                    "worktree_branch": worktree_branch,
                    "session_id": session_id,
                    "materialize_reason": materialize_reason,
                    "success": False, "cancelled": True,
                    "error": error,
                })
            # AP-123: same cleanup hint on the cancelled path.
            if isinstance(resp, dict):
                cw = resp.get("cleanup_worktree")
                cb = resp.get("cleanup_branch")
                if cw and cb:
                    self._cleanup_worktree(cw, cb)
            return

        # If the run was PAUSED, the backend already set status=PAUSED. The
        # subprocess was terminated cleanly (SIGTERM) — that exit is NOT a
        # failure. We still post back, but flagged `paused=True`: the
        # backend keeps the run PAUSED and just persists the session_id so
        # a later resume can relaunch with `claude --resume`. Without this
        # post the session handle is lost and resume starts from scratch.
        if entry and entry.get("paused"):
            logger.info("paused trace=%s — reporting session for resume "
                        "(run stays PAUSED)", trace_id)
            try:
                self.client.post_trigger_complete(
                    agent_id,
                    daemon_id=self._daemon_id,
                    trace_id=trace_id,
                    run_id=run_id,
                    success=False,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    error="",
                    session_id=session_id,
                    workdir=str(cwd_path) if cwd_path else "",
                    paused=True,
                    materialize_reason=materialize_reason,
                )
            except Exception as exc:
                logger.warning("paused-complete post failed trace=%s: %s",
                                trace_id, exc)
            if log_dir:
                self._write_run_meta(log_dir, {
                    "run_id": run_id, "trace_id": trace_id, "agent_id": agent_id,
                    "cwd": str(cwd_path) if cwd_path else "",
                    "worktree_branch": worktree_branch,
                    "session_id": session_id,
                    "materialize_reason": materialize_reason,
                    "success": False, "paused": True,
                })
            return

        # Capture git diff of the workdir if it's a repo — best-effort,
        # never fails the run on its own.
        diff_stat, diff_body = "", ""
        work_signal: dict = {"tracked": False, "untracked": False, "committed": False}
        if cwd_path:
            try:
                from agentira_cli.daemon.diff_capture import capture_with_signal
                diff_stat, diff_body, work_signal = capture_with_signal(cwd_path)
            except Exception as exc:
                logger.debug("diff capture failed trace=%s: %s", trace_id, exc)

        # Per-run meta.json: cwd, branch, session, materializer outcome,
        # exit info. Written every time we post a completion (normal +
        # cancelled + paused paths each call _write_run_meta below).
        if log_dir:
            self._write_run_meta(log_dir, {
                "run_id": run_id,
                "trace_id": trace_id,
                "agent_id": agent_id,
                "cwd": str(cwd_path) if cwd_path else "",
                "worktree_branch": worktree_branch,
                "session_id": session_id,
                "materialize_reason": materialize_reason,
                "success": success,
                "error": error,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })

        try:
            resp = self.client.post_trigger_complete(
                agent_id,
                daemon_id=self._daemon_id,
                trace_id=trace_id,
                run_id=run_id,
                success=success, input_tokens=input_tokens,
                output_tokens=output_tokens, error=error,
                diff_stat=diff_stat, diff=diff_body,
                session_id=session_id,
                workdir=str(cwd_path) if cwd_path else "",
                materialize_reason=materialize_reason,
                session_lost=session_lost,
                work_signal=work_signal,
            )
        except Exception as exc:
            logger.warning("post_trigger_complete failed trace=%s: %s", trace_id, exc)
            resp = {}

        # AP-123: backend returns cleanup_worktree + cleanup_branch on
        # terminal completions (success, fail, cancelled — NOT paused).
        # The per-run worktree we materialized at dispatch is now orphan
        # disk space — `git worktree remove` it and delete the branch.
        if isinstance(resp, dict):
            cw = resp.get("cleanup_worktree")
            cb = resp.get("cleanup_branch")
            if cw and cb:
                self._cleanup_worktree(cw, cb)

    # AP-123: tear down a per-run worktree after the backend confirms the
    # run is terminal. Best-effort — failures are logged, never raised.
    # PAUSED runs go through a different return path that doesn't carry
    # the cleanup hint, so resume can re-enter the same worktree.
    @staticmethod
    def _write_run_meta(log_dir: str, meta: dict) -> None:
        """Drop meta.json in the per-run log directory. Best-effort;
        failure is logged but doesn't break the dispatch."""
        import json
        try:
            target = os.path.join(log_dir, "meta.json")
            with open(target, "w") as f:
                json.dump(meta, f, indent=2, default=str)
        except OSError as exc:
            logger.debug("meta.json write failed (%s): %s", log_dir, exc)

    @staticmethod
    def _cleanup_worktree(worktree_path: str, worktree_branch: str) -> None:
        import os
        import subprocess
        try:
            if not worktree_path or not os.path.isdir(worktree_path):
                return
            # Resolve the source repo BEFORE removing the worktree —
            # afterward `git -C <worktree_path>` can't run (dir is gone).
            source_dir = None
            try:
                source_dir = subprocess.check_output(
                    ["git", "-C", worktree_path, "rev-parse",
                     "--show-superproject-working-tree",
                     "--git-common-dir"],
                    text=True, timeout=5,
                ).strip().splitlines()[-1]
                # --git-common-dir is `<source>/.git`; strip the suffix.
                if source_dir.endswith("/.git"):
                    source_dir = source_dir[:-5]
            except Exception:
                source_dir = None
            subprocess.run(
                ["git", "-C", worktree_path, "worktree", "remove",
                 "--force", worktree_path],
                check=False, timeout=20,
            )
            # Delete the per-run branch from the source repo (we can't
            # cwd into the now-deleted worktree).
            if worktree_branch and source_dir and os.path.isdir(source_dir):
                subprocess.run(
                    ["git", "-C", source_dir, "branch", "-D",
                     worktree_branch],
                    check=False, timeout=10,
                )
            logger.info("cleaned worktree=%s branch=%s", worktree_path,
                        worktree_branch)
        except Exception as exc:  # noqa: BLE001 — best-effort
            logger.warning("worktree cleanup failed path=%s: %s",
                           worktree_path, exc)

    # P1: SIGTERM is graceful but the subprocess can ignore it (claude-code
    # in the middle of an MCP call has been observed to take ~30s to react).
    # Schedule a SIGKILL fallback so Stop is actually reliable.
    _STOP_GRACE_S = 5.0

    @staticmethod
    def _signal_group(proc, sig: int) -> None:
        """P5: send `sig` to the whole process group claude leads.

        run_cli_stream spawns claude with start_new_session=True, so
        claude is the leader of its own session/group and `proc.pid` is
        the group id. os.killpg(pid, sig) takes down claude PLUS any
        bash-backgrounded children, MCP stdio servers, foreground tool
        subprocs — the common leak sources. Falls back to a per-PID
        signal if the spawn didn't get its own group (e.g. some
        platforms or test stand-ins).

        Detached daemon-managed children (`docker run -d`, systemd,
        double-fork) escape the group and are NOT caught here; container
        isolation (AP-83 Path B) is the structural fix for those.
        """
        if proc is None:
            return
        try:
            os.killpg(proc.pid, sig)
            return
        except ProcessLookupError:
            return  # already gone
        except (PermissionError, OSError):
            # Spawn might not have entered a new session (e.g. test
            # double doesn't set start_new_session). Fall back to a
            # plain signal so we at least kill claude itself.
            pass
        try:
            if sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
        except (ProcessLookupError, Exception):
            pass

    def _sigkill_watchdog(self, trace_id: str, proc) -> None:
        """Spawn a daemon thread that SIGKILLs `proc`'s whole group if
        it's still alive after _STOP_GRACE_S. Safe if the proc has
        already exited."""
        import threading as _th

        def _wait_then_kill() -> None:
            try:
                _th.Event().wait(self._STOP_GRACE_S)
                if proc.poll() is None:  # still alive
                    self._signal_group(proc, signal.SIGKILL)
                    logger.warning(
                        "SIGKILL fallback fired trace=%s pid=%s — "
                        "subprocess ignored SIGTERM for %.1fs",
                        trace_id, proc.pid, self._STOP_GRACE_S)
            except Exception as exc:  # noqa: BLE001
                logger.debug("sigkill watchdog ignored: %s", exc)

        _th.Thread(target=_wait_then_kill, daemon=True,
                   name=f"sigkill-watchdog-{trace_id[:8]}").start()

    def _signal_proc(self, frame: dict, signal_kind: str) -> None:
        """Pause/resume an in-flight CLI run.

        Pause does NOT freeze the process. SIGSTOP on a claude-code
        subprocess corrupts its in-flight LLM + MCP streaming sockets —
        the remote side drops the idle connection and, on resume, the
        run dies with 'subprocess exited with code 1'. That was the
        recurring run-failure bug.

        Instead, pause terminates the subprocess cleanly (SIGTERM). The
        claude session_id is captured during the run, so the backend
        resumes by re-dispatching a fresh process with `claude --resume`.
        Resume here is therefore a no-op — there is no stopped process
        to continue; a new dispatch arrives on the WS instead.

        CLI runtimes only — http_gateway has no proc to signal.
        """
        trace_id = frame.get("trace_id", "")
        run_id = frame.get("run_id", "")
        scope_key = frame.get("scope_key", "") or ""
        with self._inflight_lock:
            if not trace_id and run_id:
                trace_id = self._run_to_trace.get(run_id, "")
            # ADR 009 / B6: resolve by scope when the backend stops by scope
            # (e.g. after a backend restart that lost the trace mapping).
            if not trace_id and scope_key:
                trace_id = self._scope_to_trace.get(scope_key, "")
            entry = self._inflight.get(trace_id)
            proc = entry.get("proc") if entry else None
            if signal_kind == "pause" and entry is not None:
                entry["paused"] = True

        if signal_kind == "resume":
            logger.info("resume trace=%s — run re-dispatched with --resume",
                        trace_id or "-")
            return

        if proc is None:
            logger.info("pause for trace=%s run=%s — no live proc",
                        trace_id or "-", run_id or "-")
            return
        try:
            # P5: pause kills the whole group (claude + any bash-bg
            # children it left running). Bash-backgrounded dev servers
            # were the most common leak under the old `proc.terminate()`.
            self._signal_group(proc, signal.SIGTERM)
            logger.info("pause trace=%s — terminated group pid %s "
                        "(resumable via --resume)", trace_id, proc.pid)
            self._sigkill_watchdog(trace_id, proc)
        except (ProcessLookupError, AttributeError, Exception) as exc:
            logger.warning("pause failed for trace=%s: %s", trace_id, exc)

    def _cancel(self, frame: dict) -> None:
        """Handle a cancel frame from the WS hub.

        Resolves to a trace_id (directly given, or via the run_id map),
        marks the in-flight entry cancelled, and kills the subprocess if
        one is registered. P1: if the subprocess hasn't been bound yet
        (small race between dispatch and an immediate cancel), the
        cancelled flag is still set — on_proc kills it as soon as it's
        bound. SIGTERM is followed by a SIGKILL watchdog so the cancel
        is actually reliable.
        """
        trace_id = frame.get("trace_id", "")
        run_id = frame.get("run_id", "")
        scope_key = frame.get("scope_key", "") or ""
        with self._inflight_lock:
            if not trace_id and run_id:
                trace_id = self._run_to_trace.get(run_id, "")
            # ADR 009 / B6: resolve by scope (stop-by-scope) when neither
            # trace nor run resolves — the common path after a backend
            # restart, where the chat's trace mapping was in-memory only.
            if not trace_id and scope_key:
                trace_id = self._scope_to_trace.get(scope_key, "")
            entry = self._inflight.get(trace_id)
            if entry is not None:
                entry["cancelled"] = True
            proc = entry.get("proc") if entry else None
        if entry is None:
            # No in-memory entry. Before giving up, consult the durable
            # registry (outside the lock — a kill can take a grace pause):
            # a process may still be alive for this scope that we lost
            # track of — kill it by pid so it can't zombie.
            killed = self._cancel_via_registry(scope_key)
            logger.info("cancel: no in-memory entry trace=%s run=%s scope=%s — registry_kill=%s",
                        trace_id, run_id, scope_key or "-", killed)
            return
        logger.info("cancel trace=%s run=%s — proc_bound=%s", trace_id, run_id or "-", bool(proc))
        if proc is not None:
            try:
                # P5: group SIGTERM so bash-backgrounded children die
                # with claude; watchdog escalates to group SIGKILL.
                self._signal_group(proc, signal.SIGTERM)
                self._sigkill_watchdog(trace_id, proc)
            except (ProcessLookupError, Exception) as exc:
                logger.debug("group SIGTERM ignored: %s", exc)

    def _cancel_via_registry(self, scope_key: str) -> bool:
        """ADR 009 / B6 fallback: when there's no in-memory entry for a
        stop-by-scope, kill the process the durable registry recorded for
        the scope (if still alive). Returns True iff something was killed."""
        if not scope_key:
            return False
        try:
            from agentira_cli.daemon import inflight as _inflight_reg
            return _inflight_reg.cancel_scope(scope_key)
        except Exception as exc:  # noqa: BLE001
            logger.debug("cancel via registry failed scope=%s: %s", scope_key, exc)
            return False

    def _heartbeat(self) -> None:
        if not self._registered:
            return
        providers = [r.get("provider", "") for r in self._registered if r.get("provider")]
        # ADR 009 / B4: report the live turns from the durable registry so the
        # backend keeps a restart-proof view of what's running per scope.
        try:
            from agentira_cli.daemon import inflight as _inflight_reg
            live = _inflight_reg.list_live()
        except Exception:  # noqa: BLE001
            live = []
        try:
            self.client.heartbeat_runtimes(
                daemon_id=self._daemon_id, providers=providers, inflight=live)
        except Exception as exc:
            logger.debug("Heartbeat failed: %s", exc)
