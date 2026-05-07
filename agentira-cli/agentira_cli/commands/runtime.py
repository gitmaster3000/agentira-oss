import json as jsonlib

import typer

from ..runtimes.registry import SUPPORTED, detect_all

app = typer.Typer(help="Inspect and manage local CLI runtimes (claude, codex, ...)")


@app.command("list")
def list_runtimes(
    output: str = typer.Option("table", "--output", "-o", help="table | json"),
) -> None:
    """List detected runtimes on PATH."""
    detected = detect_all()

    if output == "json":
        typer.echo(
            jsonlib.dumps(
                [
                    {
                        "provider": d.provider,
                        "binary_path": d.binary_path,
                        "version": d.version,
                        "capabilities": d.capabilities,
                    }
                    for d in detected
                ],
                indent=2,
            )
        )
        return

    if not detected:
        typer.echo("No runtimes detected on PATH.")
        typer.echo(f"Looked for: {', '.join(c.default_binary for c in SUPPORTED)}")
        raise typer.Exit(0)

    typer.echo(f"{'PROVIDER':<12} {'VERSION':<30} {'CAPABILITIES':<30} PATH")
    for d in detected:
        caps = ",".join(d.capabilities) or "-"
        ver = (d.version or "?")[:28]
        typer.echo(f"{d.provider:<12} {ver:<30} {caps:<30} {d.binary_path}")


@app.command("detect")
def detect_one(provider: str) -> None:
    """Re-detect a specific provider (debugging)."""
    cls = next((c for c in SUPPORTED if c.provider == provider), None)
    if cls is None:
        typer.echo(f"Unknown provider: {provider}")
        typer.echo(f"Supported: {', '.join(c.provider for c in SUPPORTED)}")
        raise typer.Exit(1)
    rt = cls.detect()
    if rt is None:
        typer.echo(f"{provider}: not found on PATH")
        raise typer.Exit(1)
    typer.echo(f"{provider}: {rt.binary_path} ({rt.version or 'unknown version'})")
