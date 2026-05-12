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

        runtimes = [
            {
                "provider": d.provider,
                "binary_path": d.binary_path,
                "version": d.version,
                "capabilities": d.capabilities,
                "models": d.models,
                "gateway_url": d.gateway_url,
                "gateway_token": d.gateway_token,
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
        repo_path = frame.get("repo_path", "") or ""
        conventions_md = frame.get("conventions_md", "") or ""
        mcp_config_json = frame.get("mcp_config_json", "") or ""
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

        # Materialize the run env when we have somewhere to put it:
        # - Task runs (run_id + task_id) → per-task workdir under ~/.agentira/.
        # - Chat with a project (repo_path resolved from user_context) → write
        #   CONVENTIONS.md + courtesy symlinks straight into the repo.
        # - Free-form chat with no project → skip; runtime stays in daemon cwd.
        cwd_path = None
        if run_id and task_id:
            cwd_path, _ = materialize(
                workspace_id=agent_id,
                task_id=task_id,
                repo_path=repo_path,
                conventions_md=conventions_md,
            )
        elif repo_path:
            # Chat in a project: don't allocate a workdir, just resolve the
            # repo path so the runtime cwd is right. Materialize conventions
            # there too — repo-local, idempotent, safe.
            cwd_path, _ = materialize(
                workspace_id=agent_id,
                task_id="chat",
                repo_path=repo_path,
                conventions_md=conventions_md,
            )

        # Pre-create per-(agent, project) memory dir so the memory MCP
        # server can write on first call. Cheap and safe to always run.
        ensure_memory_dirs(mcp_config_json)
        have_memory = "memory" in (mcp_config_json or "")  # cheap probe

        # Compose the system prompt: user-context preamble + conventions +
        # memory addenda + persona, in that order.
        system_prompt = compose_system_prompt(
            agent_system_prompt,
            have_conventions=bool(cwd_path and conventions_md),
            have_memory=have_memory,
            user_context=user_context or None,
        )

        logger.info("recv trigger trace=%s kind=%s agent=%s run=%s provider=%s",
                    trace_id, kind, agent_id, run_id or "-", provider)

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
                    env_extra=env_extra,
                )
            success = result.success
            error = result.error
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
        except Exception as exc:
            error = str(exc)
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
            )
        except Exception as exc:
            logger.warning("post_trigger_complete failed trace=%s: %s", trace_id, exc)

    def _signal_proc(self, frame: dict, signal_kind: str) -> None:
        """Send SIGSTOP (pause) or SIGCONT (resume) to the in-flight
        subprocess. CLI runtimes only — http_gateway has no proc to
        signal. Best-effort; long pauses can hit LLM API timeouts."""
        import signal as _signal
        trace_id = frame.get("trace_id", "")
        run_id = frame.get("run_id", "")
        with self._inflight_lock:
            if not trace_id and run_id:
                trace_id = self._run_to_trace.get(run_id, "")
            entry = self._inflight.get(trace_id)
            proc = entry.get("proc") if entry else None
        if proc is None:
            logger.info("%s for trace=%s run=%s — no live proc to signal",
                        signal_kind, trace_id or "-", run_id or "-")
            return
        sig = _signal.SIGSTOP if signal_kind == "pause" else _signal.SIGCONT
        try:
            proc.send_signal(sig)
            logger.info("%s trace=%s — sent %s to pid %s",
                        signal_kind, trace_id, sig.name, proc.pid)
        except (ProcessLookupError, AttributeError, Exception) as exc:
            logger.warning("%s failed for trace=%s: %s", signal_kind, trace_id, exc)

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
