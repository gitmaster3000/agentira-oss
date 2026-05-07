import typer

from .commands import daemon as daemon_cmd
from .commands import runtime as runtime_cmd

app = typer.Typer(
    name="agentira",
    help="AgentIRA local CLI — runtime detection and daemon management.",
    no_args_is_help=True,
)
app.add_typer(runtime_cmd.app, name="runtime")
app.add_typer(daemon_cmd.app, name="daemon")


if __name__ == "__main__":
    app()
