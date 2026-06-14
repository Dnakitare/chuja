"""Resolve a user-supplied source (local path or URL) to a local audio file.

The URL path imports ``yt_dlp`` lazily so the core install stays free of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .errors import FetchError, MissingDependencyError, SourceError
from .util import is_url, require_ffmpeg, safe_name


@dataclass
class ResolvedSource:
    path: Path          # local audio file ready to feed to the separator
    title: str          # human-readable track name (used for output folder)
    is_temporary: bool  # True if we downloaded it and should clean it up


# Common audio/video containers we accept as local input. Demucs/ffmpeg can read
# far more; this is just a sanity check for nicer error messages.
_AUDIO_SUFFIXES = {
    ".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus",
    ".wma", ".aiff", ".aif", ".mp4", ".webm", ".mkv", ".mov",
}


def resolve(
    source: str,
    *,
    workdir: Path,
    on_event: Optional[Callable[[str], None]] = None,
) -> ResolvedSource:
    """Resolve ``source`` to a local file. Downloads first if it is a URL."""
    if is_url(source):
        return _fetch_url(source, workdir=workdir, on_event=on_event)
    return _resolve_local(source)


def _resolve_local(source: str) -> ResolvedSource:
    path = Path(source).expanduser()
    if not path.exists():
        raise SourceError(f"File not found: {path}")
    if path.is_dir():
        raise SourceError(f"Expected an audio file but got a directory: {path}")
    if path.suffix.lower() not in _AUDIO_SUFFIXES:
        raise SourceError(
            f"Unsupported file type '{path.suffix}'. Expected an audio/video file "
            f"(e.g. {', '.join(sorted(_AUDIO_SUFFIXES))})."
        )
    return ResolvedSource(path=path, title=path.stem, is_temporary=False)


def _fetch_url(
    url: str,
    *,
    workdir: Path,
    on_event: Optional[Callable[[str], None]],
) -> ResolvedSource:
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise MissingDependencyError(
            "URL input requires the optional 'url' extra. Install it with:\n"
            "  pip install 'chuja[url]'\n"
            "You are responsible for complying with each platform's Terms of "
            "Service and applicable copyright law when downloading audio."
        ) from exc

    require_ffmpeg()  # yt-dlp needs it to extract a clean audio track
    if on_event:
        on_event(f"Fetching audio from {url}")

    # Pull the best audio-only stream and hand the raw file straight to Demucs;
    # we deliberately do NOT transcode here so no quality is lost before
    # separation. Demucs reads the source container directly via ffmpeg.
    outtmpl = str(workdir / "%(id)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nopart": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded = Path(ydl.prepare_filename(info))
    except Exception as exc:  # yt-dlp raises a wide variety of error types
        raise FetchError(f"Could not download audio from {url}: {exc}") from exc

    if not downloaded.exists():
        # Some extractors rename on post-processing; fall back to the newest file.
        candidates = sorted(workdir.glob("*"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            raise FetchError(f"Download reported success but no file was produced for {url}")
        downloaded = candidates[-1]

    title = safe_name(info.get("title") or downloaded.stem)
    return ResolvedSource(path=downloaded, title=title, is_temporary=True)
