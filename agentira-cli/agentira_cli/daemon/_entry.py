"""Background daemon entry point — spawned by `agentira daemon start`."""

from agentira_cli.commands.daemon import DaemonConfig, _run_daemon

if __name__ == "__main__":
    _run_daemon(DaemonConfig())
