import typer

from agentira_cli.state.env_file import emit_config_warnings, load_cli_env_files

# Env files must load before importing command modules that read env at
# import time, so these imports intentionally follow the call above.
emit_config_warnings(load_cli_env_files())

from .commands import daemon as daemon_cmd  # noqa: E402
from .commands import runtime as runtime_cmd  # noqa: E402
from ._version import get_version  # noqa: E402

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
