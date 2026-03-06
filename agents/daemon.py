"""Agentira Daemon — background task executor powered by ZeroClaw.

Usage::

    # Normal mode (requires a local ZeroClaw agent running)
    python -m agents.daemon

    # Dry-run mode (logs actions, skips ZeroClaw)
    python -m agents.daemon --dry-run

    # Custom poll interval
    AGENTIRA_DAEMON_POLL_INTERVAL=60 python -m agents.daemon
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import signal
import sys
import threading
import traceback
from datetime import datetime, timezone

from agents.config import DaemonConfig
from agents.agentira_client import AgentiraClient
from agents.webhook_receiver import WebhookReceiver

# ── Logging setup ────────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logger = logging.getLogger("agentira_daemon")

PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _setup_logging(level: str) -> None:
    """Configure daemon logging to file + stderr."""
    log_file = os.path.join(LOG_DIR, "daemon.log")
    fmt = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


# ── Daemon ───────────────────────────────────────────────────────────────


class AgentiraDaemon:
    """Background daemon that polls Agentira for tasks and executes them."""

    def __init__(self, config: DaemonConfig) -> None:
        self.config = config
        self._running = False
        self._wake_event = threading.Event()
        self._webhook_queue: queue.Queue = queue.Queue()
        self.client = AgentiraClient(
            base_url=config.api_url,
            api_key=config.api_key,
            bot_name=config.bot_name,
        )
        self._receiver = WebhookReceiver(
            port=config.webhook_port,
            event_queue=self._webhook_queue,
            wake_event=self._wake_event,
            token=config.webhook_token,
        )

    # ── Lifecycle ────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the main loop.  Blocks until shutdown signal."""
        self._running = True
        self._install_signal_handlers()
        self._receiver.start()

        logger.info(
            "Daemon started — bot=%s  poll=%ds  webhook_port=%s  dry_run=%s",
            self.config.bot_name,
            self.config.poll_interval,
            self.config.webhook_port or "disabled",
            self.config.dry_run,
        )

        # Initial poll on startup
        self._run_cycle()

        while self._running:
            # Interrupt-aware sleep: wake early on webhook push or signal
            woken_by_webhook = self._wake_event.wait(timeout=self.config.poll_interval)
            if not self._running:
                break
            self._wake_event.clear()

            if woken_by_webhook:
                logger.debug("Woken by webhook push — draining queue")
                self._drain_webhook_queue()

            self._run_cycle()

        self.shutdown()

    def shutdown(self) -> None:
        """Clean up resources."""
        self._running = False
        self._receiver.stop()
        logger.info("Daemon shutting down.")
        self.client.close()

    # ── Signal handling ──────────────────────────────────────────────────

    def _install_signal_handlers(self) -> None:
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum: int, frame: object) -> None:  # noqa: ARG002
        logger.info("Received signal %d — stopping after current cycle.", signum)
        self._running = False

    # ── Core loop ────────────────────────────────────────────────────────

    def _drain_webhook_queue(self) -> None:
        """Log webhook push payloads (events wake the loop; execution is via poll)."""
        while not self._webhook_queue.empty():
            try:
                payload = self._webhook_queue.get_nowait()
                logger.debug(
                    "Webhook event dequeued: %s task=%s",
                    payload.get("event"), payload.get("task_id"),
                )
            except queue.Empty:
                break

    def _poll_notifications(self) -> None:
        """Consume unread notifications — durable fallback for missed webhooks.

        The notification DB row is written before the webhook fires, so any
        event missed due to network failure or daemon restart is recovered here.
        """
        try:
            notifications = self.client.get_notifications(unread_only=True)
            if not notifications:
                return
            logger.info("Notification poll: %d unread", len(notifications))
            for n in notifications:
                logger.info("Notification [%s] %s", n.get("type"), n.get("title"))
                self.client.mark_notification_read(n["id"])
        except Exception as exc:
            logger.warning("Notification poll failed: %s", exc)

    def _run_cycle(self) -> None:
        """Run one poll-and-execute cycle, with error isolation."""
        try:
            self._poll_notifications()
            self.poll_and_execute()
        except KeyboardInterrupt:
            self._running = False
        except Exception:
            logger.error("Unhandled error in poll cycle:\n%s", traceback.format_exc())

    def poll_and_execute(self) -> None:
        """Single poll cycle: find a task, execute it, report back."""
        logger.info("Polling for tasks assigned to '%s'…", self.config.bot_name)

        # 1. Check in-progress tasks first (resume interrupted work)
        tasks = self.client.list_my_tasks(status="in_progress")
        if tasks:
            task = self.pick_task(tasks)
            logger.info("Resuming in-progress task: %s — %s", task["id"], task["title"])
            self.execute_task(task)
            return

        # 2. Pick from todo
        tasks = self.client.list_my_tasks(status="todo")
        if tasks:
            task = self.pick_task(tasks)
            logger.info("Picked todo task: %s — %s", task["id"], task["title"])
            self.client.move_task(task["id"], "in_progress")
            self.execute_task(task)
            return

        # 3. Check backlog as a fallback
        tasks = self.client.list_my_tasks(status="backlog")
        if tasks:
            task = self.pick_task(tasks)
            logger.info("Picked backlog task: %s — %s", task["id"], task["title"])
            self.client.move_task(task["id"], "in_progress")
            self.execute_task(task)
            return

        logger.info("No tasks found. Will retry in %ds.", self.config.poll_interval)

    # ── Task selection ───────────────────────────────────────────────────

    @staticmethod
    def pick_task(tasks: list[dict]) -> dict:
        """Pick the highest-priority task.  Critical > High > Medium > Low."""
        return min(tasks, key=lambda t: PRIORITY_ORDER.get(t.get("priority", "medium"), 2))

    # ── Execution ────────────────────────────────────────────────────────

    def execute_task(self, task: dict) -> None:
        """Execute a single task via ZeroClaw and report the result."""
        task_id = task["id"]
        title = task.get("title", "Untitled")
        description = task.get("description", "")
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        # Build the prompt
        prompt = self._build_prompt(title, description)

        # Comment that we're starting
        self.client.add_comment(
            task_id,
            f"🤖 **Daemon picked up this task** at {timestamp}\n\nPrompt sent to agent:\n```\n{prompt[:500]}\n```",
        )

        if self.config.dry_run:
            logger.info("[DRY RUN] Would execute task %s with prompt:\n%s", task_id, prompt[:200])
            self.client.add_comment(task_id, "🏁 [DRY RUN] Execution skipped — dry_run mode enabled.")
            return

        try:
            result = self._run(prompt, task)
            result_text = result.text if hasattr(result, "text") else str(result)
            success = result.success if hasattr(result, "success") else True

            if success:
                logger.info("Task %s completed successfully.", task_id)
                self.client.add_comment(
                    task_id,
                    f"✅ **Agent completed the task.**\n\n{result_text[:2000]}",
                )
                self.client.move_task(task_id, "review")
            else:
                error_msg = result.error if hasattr(result, "error") else "Unknown error"
                logger.warning("Task %s agent returned failure: %s", task_id, error_msg)
                self.client.add_comment(
                    task_id,
                    f"⚠️ **Agent returned failure.**\n\n{error_msg[:1000]}",
                )

        except Exception as e:
            logger.error("Task %s execution error: %s\n%s", task_id, e, traceback.format_exc())
            self.client.add_comment(
                task_id,
                f"❌ **Daemon error during execution:**\n```\n{str(e)[:800]}\n```",
            )

    def _run(self, prompt: str, task: dict) -> object:
        """Dispatch to the configured executor backend.

        'zeroclaw'  — local ZeroClaw SDK
        'http'      — OpenAI-compatible HTTP endpoint (OpenClaw, any LLM gateway)
        """
        executor = self.config.executor
        logger.debug("Executor: %s", executor)
        if executor == "http":
            return self._run_http(prompt, task)
        if executor == "cli":
            return self._run_cli(prompt, task)
        return self._run_zeroclaw(prompt, task)

    def _run_zeroclaw(self, prompt: str, task: dict) -> object:  # noqa: ARG002
        """Execute prompt via local ZeroClaw agent."""
        from zeroclaw import ZeroClaw
        from cmdop.models.agent import AgentRunOptions

        client = ZeroClaw.local(port=self.config.zeroclaw_port)
        try:
            options = AgentRunOptions(max_turns=self.config.max_agent_turns)
            return client.agent.run(prompt, options=options)
        finally:
            client.close()

    def _run_http(self, prompt: str, task: dict) -> object:
        """Execute prompt via any OpenAI-compatible HTTP endpoint.

        Works with OpenClaw (/v1/chat/completions), ZeroClaw HTTP mode,
        or any other OpenAI-compatible agent gateway.

        Config: executor_url, executor_token, executor_model.
        The model field is used by the gateway to route to the right agent.
        """
        import json
        import urllib.request

        model = self.config.executor_model or task.get("assignee", "main")
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()

        req = urllib.request.Request(
            self.config.executor_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.executor_token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read())

        text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

        class _Result:
            success = True

        result = _Result()
        result.text = text
        return result

    def _run_cli(self, prompt: str, task: dict) -> object:
        """Execute prompt via a local CLI agent (prompt → stdin, stdout → result).

        Works with OpenClaw CLI, ZeroClaw CLI, or any agent binary on the same machine.

        Config: executor_command — supports {assignee} placeholder for agent routing.
        Example: "openclaw chat --agent {assignee}"
        """
        import subprocess
        import shlex

        command = self.config.executor_command.format(
            assignee=task.get("assignee", "main"),
        )
        logger.debug("CLI executor: %s", command)

        proc = subprocess.run(
            shlex.split(command),
            input=prompt,
            capture_output=True,
            text=True,
            timeout=300,
        )

        class _Result:
            pass

        result = _Result()
        result.success = proc.returncode == 0
        result.text    = proc.stdout.strip() if proc.returncode == 0 else proc.stderr.strip()
        result.error   = proc.stderr.strip() if proc.returncode != 0 else ""
        return result

    @staticmethod
    def _build_prompt(title: str, description: str) -> str:
        """Build the agent prompt from task metadata."""
        parts = [f"# Task: {title}"]
        if description:
            parts.append(f"\n## Description\n{description}")
        parts.append(
            "\n## Instructions\n"
            "Work on this task. Use the tools available to you (terminal, files, etc.) "
            "to complete it. When done, provide a summary of what you did."
        )
        return "\n".join(parts)


# ── CLI entry point ──────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Agentira ZeroClaw Daemon")
    parser.add_argument("--dry-run", action="store_true", help="Log actions without executing via ZeroClaw")
    parser.add_argument("--poll-interval", type=int, help="Override poll interval (seconds)")
    parser.add_argument("--api-key", type=str, help="Agentira bot API key")
    parser.add_argument("--bot-name", type=str, help="Bot profile name")
    args = parser.parse_args()

    # Load config from env, then override with CLI args
    config = DaemonConfig()

    if args.dry_run:
        config.dry_run = True
    if args.poll_interval:
        config.poll_interval = args.poll_interval
    if args.api_key:
        config.api_key = args.api_key
    if args.bot_name:
        config.bot_name = args.bot_name

    # Validate
    if not config.api_key:
        print("ERROR: No API key provided. Set AGENTIRA_DAEMON_API_KEY or use --api-key.", file=sys.stderr)
        sys.exit(1)

    if not config.bot_name:
        print("ERROR: No bot name provided. Set AGENTIRA_DAEMON_BOT_NAME or use --bot-name.", file=sys.stderr)
        sys.exit(1)

    _setup_logging(config.log_level)

    daemon = AgentiraDaemon(config)
    daemon.run()


if __name__ == "__main__":
    main()
