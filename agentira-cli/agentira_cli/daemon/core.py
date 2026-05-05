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
            # Drain pending tasks from the WS queue
            while True:
                try:
                    frame = self._task_queue.get_nowait()
                except queue.Empty:
                    break
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
        """Execute a single task frame dispatched from the WS hub."""
        from agentira_cli.daemon.executor import run_cli_stream, run_gateway

        run_id = frame.get("run_id", "")
        chat_id = frame.get("chat_id", "")
        agent_id = frame.get("agent_id", "")
        prompt = frame.get("prompt", "")
        provider = frame.get("provider", "")
        is_chat = not run_id and bool(chat_id)

        runtime_cls = get_runtime_cls(provider)
        if runtime_cls is None:
            logger.warning("Unknown provider '%s' in frame run=%s chat=%s", provider, run_id, chat_id)
            return

        # Determine capability and routing info from the registered runtime record
        runtime_info = next(
            (r for r in self._registered if r.get("provider") == provider), {}
        )
        capabilities = runtime_info.get("capabilities", [])
        binary_path = runtime_info.get("binary_path", "")
        gateway_url = frame.get("gateway_url") or runtime_info.get("gateway_url", "")
        gateway_token = frame.get("gateway_token") or runtime_info.get("gateway_token", "")
        model = frame.get("model", runtime_info.get("models", [""])[0] if runtime_info.get("models") else "")
        system_prompt = frame.get("system_prompt", "")
        agent_name = frame.get("agent_name", "")

        async def on_event(evts: list) -> None:
            try:
                if is_chat:
                    self.client.post_agent_chat_events(agent_id, self._daemon_id, chat_id, list(evts))
                else:
                    self.client.post_run_events(run_id, self._daemon_id, list(evts))
            except Exception as exc:
                logger.warning("post_events failed: %s", exc)

        success = False
        error = ""
        input_tokens = 0
        output_tokens = 0
        try:
            if "http_gateway" in capabilities:
                result = await run_gateway(
                    gateway_url, gateway_token, agent_name, prompt,
                    model=model, system_prompt=system_prompt, on_event=on_event,
                )
            else:
                result = await run_cli_stream(
                    runtime_cls, binary_path, prompt,
                    model=model, system_prompt=system_prompt, on_event=on_event,
                )
            success = result.success
            error = result.error
            input_tokens = result.input_tokens
            output_tokens = result.output_tokens
        except Exception as exc:
            error = str(exc)
            logger.exception("Task execution failed run=%s chat=%s", run_id, chat_id)

        # Only close out a run — chat is ephemeral
        if not is_chat:
            try:
                self.client.complete_run(
                    run_id, self._daemon_id,
                    success=success, input_tokens=input_tokens,
                    output_tokens=output_tokens, error=error,
                )
            except Exception as exc:
                logger.warning("complete_run failed: %s", exc)

    def _heartbeat(self) -> None:
        if not self._registered:
            return
        providers = [r.get("provider", "") for r in self._registered if r.get("provider")]
        try:
            self.client.heartbeat_runtimes(daemon_id=self._daemon_id, providers=providers)
        except Exception as exc:
            logger.debug("Heartbeat failed: %s", exc)
