"""ASCII wordmark + a small startup animation for the CLI.

All animation auto-disables when stdout is not a TTY (piped/redirected), so
scripts and captured output stay clean."""

from __future__ import annotations

import sys
import time

from rich.console import Console
from rich.text import Text

# Block wordmark. Kept as plain rows so we can color/animate per line.
_LOGO = [
    " ██████ ██   ██ ██   ██     ███  █████ ",
    "██      ██   ██ ██   ██      ██ ██   ██",
    "██      ███████ ██   ██      ██ ███████",
    "██      ██   ██ ██   ██ ██   ██ ██   ██",
    " ██████ ██   ██  █████   █████  ██   ██",
]

# warm amber gradient top→bottom
_SHADES = ["#ffb38f", "#ff8c5a", "#ff6b35", "#ef5a28", "#d44a1c"]


def _is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def show(console: Console | None = None, *, animate: bool | None = None, tagline: str = "stem console") -> None:
    """Render the wordmark. Animates a staggered reveal + a tiny VU flourish
    when attached to a terminal."""
    console = console or Console()
    if animate is None:
        animate = _is_tty()

    console.print()
    for i, row in enumerate(_LOGO):
        line = Text("  " + row, style=f"bold {_SHADES[i]}")
        console.print(line)
        if animate:
            time.sleep(0.05)

    sub = Text("  ", style="")
    sub.append("│ ", style="#474c54")
    sub.append(tagline.upper(), style="bold #d7dbe0")
    sub.append("  ·  ", style="#474c54")
    sub.append("local neural stem separation", style="#767c85")
    console.print(sub)

    if animate:
        _vu(console)
    console.print()


def _vu(console: Console, frames: int = 14) -> None:
    """A brief equalizer flourish under the wordmark."""
    import random  # local: only used in the animated TTY path

    bars = 28
    heights = [0] * bars
    blocks = " ▁▂▃▄▅▆▇█"
    for _ in range(frames):
        line = Text("  ")
        for b in range(bars):
            target = random.randint(0, 8)
            heights[b] = (heights[b] + target) // 2
            shade = _SHADES[min(len(_SHADES) - 1, heights[b] // 2)]
            line.append(blocks[heights[b]], style=shade)
        console.print(line, end="\r")
        time.sleep(0.045)
    # clear the flourish line
    console.print(Text(" " * (bars + 4)), end="\r")
