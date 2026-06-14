"""Small, dependency-free helpers. Importable without torch/demucs present."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

_URL_SCHEMES = {"http", "https"}

# Characters that are unsafe across macOS / Windows / Linux filesystems.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE = re.compile(r"\s+")


def is_url(source: str) -> bool:
    """True if ``source`` looks like an http(s) URL rather than a local path."""
    try:
        parsed = urlparse(source.strip())
    except (ValueError, AttributeError):
        return False
    return parsed.scheme in _URL_SCHEMES and bool(parsed.netloc)


def safe_name(name: str, *, fallback: str = "track", max_len: int = 120) -> str:
    """Turn an arbitrary track title into a filesystem-safe folder name.

    Strips path separators and control characters, collapses whitespace, and
    trims trailing dots/spaces (which Windows rejects)."""
    cleaned = _UNSAFE.sub(" ", name)
    cleaned = _WHITESPACE.sub(" ", cleaned).strip(" .")
    cleaned = cleaned[:max_len].strip(" .")
    return cleaned or fallback


def require_ffmpeg() -> str:
    """Return the path to ffmpeg or raise a clear, actionable error.

    ffmpeg is needed both by yt-dlp (audio extraction) and for mp3/flac export."""
    from .errors import MissingDependencyError

    path = shutil.which("ffmpeg")
    if path is None:
        raise MissingDependencyError(
            "ffmpeg was not found on your PATH. Install it:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows: winget install Gyan.FFmpeg"
        )
    return path


def unique_dir(parent: Path, name: str) -> Path:
    """Return ``parent/name``, suffixing -2, -3, ... if it already exists,
    so a second run on the same track never clobbers earlier output."""
    candidate = parent / name
    i = 2
    while candidate.exists():
        candidate = parent / f"{name}-{i}"
        i += 1
    return candidate
