"""AgentIRA daemon — runtime host.

Detects local CLI runtimes, registers them with the server, sends heartbeats,
and listens on a WebSocket for `task_available` push frames. Task execution
is dispatched per-frame; there is no per-bot polling.
"""

from __future__ import annotations

import asyncio
import logging
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
        self._inflight_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        self._install_signal_handlers()

        self._registered = self._register_runtimes()

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
        try:
            if run_id and task_id:
                logger.info("step=materialize trace=%s (task run)", trace_id)
                cwd_path, _ = await asyncio.wait_for(
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
                cwd_path, _ = await asyncio.wait_for(
                    asyncio.to_thread(
                        materialize,
                        workspace_id=agent_id,
                        task_id="chat",
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
            self._inflight[trace_id] = {"proc": None, "cancelled": False}
            if run_id:
                self._run_to_trace[run_id] = trace_id

        def on_proc(proc):
            with self._inflight_lock:
                entry = self._inflight.get(trace_id)
                if entry is not None:
                    entry["proc"] = proc

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
        if entry and entry.get("cancelled"):
            success = False
            error = "Cancelled by user."

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
                    paused=True,
                )
            except Exception as exc:
                logger.warning("paused-complete post failed trace=%s: %s",
                                trace_id, exc)
            return

        # Capture git diff of the workdir if it's a repo — best-effort,
        # never fails the run on its own.
        diff_stat, diff_body = "", ""
        if cwd_path:
            try:
                from agentira_cli.daemon.diff_capture import capture
                diff_stat, diff_body = capture(cwd_path)
            except Exception as exc:
                logger.debug("diff capture failed trace=%s: %s", trace_id, exc)

        try:
            self.client.post_trigger_complete(
                agent_id,
                daemon_id=self._daemon_id,
                trace_id=trace_id,
                run_id=run_id,
                success=success, input_tokens=input_tokens,
                output_tokens=output_tokens, error=error,
                diff_stat=diff_stat, diff=diff_body,
                session_id=session_id,
                workdir=str(cwd_path) if cwd_path else "",
            )
        except Exception as exc:
            logger.warning("post_trigger_complete failed trace=%s: %s", trace_id, exc)

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
        with self._inflight_lock:
            if not trace_id and run_id:
                trace_id = self._run_to_trace.get(run_id, "")
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
            proc.terminate()  # SIGTERM — graceful stop, NOT SIGSTOP
            logger.info("pause trace=%s — terminated pid %s "
                        "(resumable via --resume)", trace_id, proc.pid)
        except (ProcessLookupError, AttributeError, Exception) as exc:
            logger.warning("pause failed for trace=%s: %s", trace_id, exc)

    def _cancel(self, frame: dict) -> None:
        """Handle a cancel frame from the WS hub.

        Resolves to a trace_id (directly given, or via the run_id map),
        marks the in-flight entry cancelled, and kills the subprocess
        if one is registered. The execute loop notices the kill on
        stdout EOF and the cancelled flag drives the complete payload.
        """
        trace_id = frame.get("trace_id", "")
        run_id = frame.get("run_id", "")
        with self._inflight_lock:
            if not trace_id and run_id:
                trace_id = self._run_to_trace.get(run_id, "")
            entry = self._inflight.get(trace_id)
            if entry is None:
                logger.info("cancel for unknown trace=%s run=%s — already finished", trace_id, run_id)
                return
            entry["cancelled"] = True
            proc = entry.get("proc")
        logger.info("cancel trace=%s run=%s — killing proc=%s", trace_id, run_id or "-", bool(proc))
        if proc is not None:
            try:
                proc.kill()
            except (ProcessLookupError, Exception) as exc:
                logger.debug("proc.kill ignored: %s", exc)

    def _heartbeat(self) -> None:
        if not self._registered:
            return
        providers = [r.get("provider", "") for r in self._registered if r.get("provider")]
        try:
            self.client.heartbeat_runtimes(daemon_id=self._daemon_id, providers=providers)
        except Exception as exc:
            logger.debug("Heartbeat failed: %s", exc)
