"""Command-line interface for chuja."""

from __future__ import annotations

import sys
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

import click
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from typer.core import TyperGroup

from . import __version__, banner
from .errors import ChujaError
from .pipeline import separate as run_separate
from .separator import DEFAULT_MODEL, MODELS

# Windows consoles often default to cp1252, which can't encode the UI glyphs
# (✓, box-drawing, the banner blocks) and raises UnicodeEncodeError mid-output.
# Force UTF-8 so output never crashes regardless of the host console. Must run
# before the Console objects below read the stream encoding.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

console = Console()
err_console = Console(stderr=True)


class DefaultGroup(TyperGroup):
    """Let `chuja song.mp3` work as a shortcut for `chuja separate song.mp3`."""

    def resolve_command(self, ctx, args):
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            if not args:
                raise
            return super().resolve_command(ctx, ["separate", *args])


app = typer.Typer(
    cls=DefaultGroup,
    add_completion=False,
    help="Separate a song into stems (vocals/drums/bass/other). "
    "Run `chuja` with no arguments for interactive mode, or `chuja serve` for the visual console.",
    rich_markup_mode="rich",
)


def _version_callback(value: bool):
    if value:
        console.print(f"chuja {__version__}")
        raise typer.Exit()


# ----------------------------------------------------------------------------
# separate
# ----------------------------------------------------------------------------
@app.command()
def separate(
    source: str = typer.Argument(..., help="Audio file path, or a URL (needs the 'url' extra)."),
    out: Path = typer.Option("stems", "--out", "-o", help="Directory to write the stem folder into."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Separation model. See `chuja models`."),
    fmt: str = typer.Option("wav", "--format", "-f", help="Output format: wav, mp3, or flac."),
    two_stems: Optional[str] = typer.Option(None, "--two-stems", help="One stem + accompaniment, e.g. vocals."),
    mp3_bitrate: int = typer.Option(320, "--mp3-bitrate", help="kbps for mp3 export."),
    zip_output: bool = typer.Option(False, "--zip", help="Also bundle the stems into a portable .zip."),
    device: Optional[str] = typer.Option(None, "--device", help="Force a torch device: cpu, cuda, or mps."),
    open_folder: bool = typer.Option(False, "--open", "-O", help="Reveal the output folder in your file manager when done."),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress the banner and progress chatter."),
):
    """Separate SOURCE into stems."""
    if not quiet:
        banner.show(console)

    def on_event(message: str):
        if not quiet:
            console.print(f"  [dim]›[/] {message}")

    try:
        result = run_separate(
            source, out_dir=out, model=model, two_stems=two_stems, fmt=fmt,
            mp3_bitrate=mp3_bitrate, zip_output=zip_output, device=device, on_event=on_event,
        )
    except ChujaError as exc:
        err_console.print(f"\n[bold red]✗ Error:[/] {exc}")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:  # pragma: no cover
        err_console.print("\n[yellow]Cancelled.[/]")
        raise typer.Exit(code=130)

    _print_result(result, fmt)
    if open_folder:
        _reveal(result.out_dir)


def _reveal_command() -> str:
    """The platform-native 'open this folder' command, for the copy-paste hint."""
    if sys.platform == "darwin":
        return "open"
    if sys.platform.startswith("win"):
        return "explorer"
    return "xdg-open"


def _reveal(path: Path) -> bool:
    """Open a folder in the OS file manager. Best-effort; never raises."""
    import subprocess

    target = str(Path(path).resolve())
    try:
        if sys.platform.startswith("win"):
            import os
            os.startfile(target)  # type: ignore[attr-defined]
        else:
            subprocess.run([_reveal_command(), target], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _print_result(result, fmt):
    out_dir = Path(result.out_dir).resolve()
    body = Text()
    body.append(f"{result.track}\n\n", style="bold #ff6b35")
    # The folder, front and center — absolute so it's unambiguous and clickable.
    body.append("folder  ", style="#767c85")
    body.append(f"{out_dir}\n", style="bold #d7dbe0")
    for name, path in result.stems.items():
        body.append(f"        {name:<13}", style="#29d3c2")
        body.append(f"{Path(path).name}\n", style="dim")
    if result.archive:
        body.append("        ", style="")
        body.append(f"{'zip':<13}", style="#b56bff")
        body.append(f"{Path(result.archive).name}\n", style="dim")
    body.append("\nreveal  ", style="#767c85")
    body.append(f'{_reveal_command()} "{out_dir}"', style="#29d3c2")
    console.print()
    console.print(Panel(body, title=f"[bold green]✓ {len(result.stems)} stems · {fmt}[/]",
                        subtitle="[dim]rerun with --open to jump straight to the folder[/]",
                        border_style="#34383e", expand=False))


# ----------------------------------------------------------------------------
# serve
# ----------------------------------------------------------------------------
@app.command()
def serve(
    out: Path = typer.Option(
        Path(tempfile.gettempdir()) / "chuja-stems", "--out", "-o",
        help="Where the console writes stems.",
    ),
    port: int = typer.Option(7777, "--port", "-p", help="Port to listen on."),
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind (localhost by default)."),
    model: str = typer.Option(DEFAULT_MODEL, "--model", "-m", help="Default model for the console."),
    no_open: bool = typer.Option(False, "--no-open", help="Don't auto-open the browser."),
):
    """Launch the visual mixing console in your browser."""
    _serve(out=out, port=port, host=host, model=model, no_open=no_open)


def _serve(
    *,
    out: Optional[Path] = None,
    port: int = 7777,
    host: str = "127.0.0.1",
    model: str = DEFAULT_MODEL,
    no_open: bool = False,
):
    """Plain implementation shared by the `serve` command and interactive mode.

    Kept separate because Typer command functions can't be called directly —
    their parameter defaults are OptionInfo descriptors, not values."""
    from . import server  # local import: avoids loading the server unless used

    if out is None:
        out = Path(tempfile.gettempdir()) / "chuja-stems"

    banner.show(console, tagline="visual console")
    try:
        httpd, url = server.serve(out_dir=out, host=host, port=port, model=model)
    except OSError as exc:
        err_console.print(f"[bold red]✗[/] Could not bind {host}:{port} — {exc}")
        err_console.print("  Try another port:  [bold]chuja serve --port 7788[/]")
        raise typer.Exit(code=1)

    panel = Text()
    panel.append("  console live at  ", style="#767c85")
    panel.append(url, style="bold #ff6b35 underline")
    panel.append("\n  output folder    ", style="#767c85")
    panel.append(str(Path(out)), style="dim")
    panel.append("\n\n  drop a file or paste a URL in the browser.", style="#d7dbe0")
    panel.append("\n  press ", style="#767c85")
    panel.append("Ctrl+C", style="bold #29d3c2")
    panel.append(" here to stop.", style="#767c85")
    console.print(Panel(panel, border_style="#34383e", title="[bold]▶ chuja serve[/]", expand=False))

    if not no_open:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]console stopped.[/]")
    finally:
        httpd.server_close()


# ----------------------------------------------------------------------------
# models
# ----------------------------------------------------------------------------
@app.command()
def models():
    """List available separation models."""
    table = Table(title="Demucs models", border_style="#34383e", title_style="bold #ff6b35")
    table.add_column("Model", style="#29d3c2", no_wrap=True)
    table.add_column("Description", style="#d7dbe0")
    for name, desc in MODELS.items():
        label = f"{name}  (default)" if name == DEFAULT_MODEL else name
        table.add_row(label, desc)
    console.print(table)


# ----------------------------------------------------------------------------
# interactive (bare `chuja`)
# ----------------------------------------------------------------------------
def interactive():
    """A small guided flow when the user runs `chuja` with no arguments."""
    from rich.prompt import Prompt

    if not sys.stdin.isatty():
        # Non-interactive context (piped/CI): show help instead of hanging.
        command = typer.main.get_command(app)
        with click.Context(command) as ctx:
            console.print(ctx.get_help())
        return

    banner.show(console)
    console.print("  [bold]What would you like to do?[/]\n")
    console.print("   [#ff6b35]1[/]  Separate a local file")
    console.print("   [#ff6b35]2[/]  Separate from a URL")
    console.print("   [#ff6b35]3[/]  Launch the visual console  [dim](web UI)[/]")
    console.print("   [#ff6b35]q[/]  Quit\n")
    choice = Prompt.ask("  [bold]›[/]", choices=["1", "2", "3", "q"], default="3", show_choices=False)

    if choice == "q":
        return
    if choice == "3":
        return _serve()

    source = Prompt.ask("  [#29d3c2]file path[/]" if choice == "1" else "  [#29d3c2]url[/]")
    model = Prompt.ask("  model", choices=list(MODELS), default=DEFAULT_MODEL, show_choices=False)
    fmt = Prompt.ask("  format", choices=["wav", "mp3", "flac"], default="mp3")
    split = Prompt.ask("  split", choices=["full", "karaoke"], default="full")
    two = "vocals" if split == "karaoke" else None
    bundle = Prompt.ask("  zip the stems?", choices=["y", "n"], default="y") == "y"

    def on_event(message: str):
        console.print(f"  [dim]›[/] {message}")

    try:
        result = run_separate(source, out_dir="stems", model=model, two_stems=two,
                              fmt=fmt, zip_output=bundle, on_event=on_event)
    except ChujaError as exc:
        err_console.print(f"\n[bold red]✗ Error:[/] {exc}")
        raise typer.Exit(code=1)
    _print_result(result, fmt)
    if Prompt.ask("  reveal the folder?", choices=["y", "n"], default="y") == "y":
        _reveal(result.out_dir)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True, help="Show version and exit."),
):
    """chuja — stem separation for the command line."""
    if ctx.invoked_subcommand is None:
        interactive()
        raise typer.Exit()


if __name__ == "__main__":  # pragma: no cover
    app()
