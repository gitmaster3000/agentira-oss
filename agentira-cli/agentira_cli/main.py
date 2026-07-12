import typer

from agentira_cli.state.env_file import load_cli_env_files

load_cli_env_files()

from .commands import daemon as daemon_cmd
from .commands import runtime as runtime_cmd
from ._version import get_version

app = typer.Typer(
    name="agentira",
    help="AgentIRA local CLI — runtime detection and daemon management.",
    no_args_is_help=True,
)
app.add_typer(runtime_cmd.app, name="runtime")
app.add_typer(daemon_cmd.app, name="daemon")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"agentira-cli {get_version()}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False, "--version", "-V", callback=_version_callback, is_eager=True,
        help="Show installed CLI version and exit.",
    ),
) -> None:
    """AgentIRA local CLI."""


if __name__ == "__main__":
    app()
