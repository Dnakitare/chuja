"""End-to-end orchestration: source -> stems -> files. The public entrypoint."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from . import export, separator, sources
from .separator import DEFAULT_MODEL
from .util import safe_name, unique_dir

EventHook = Optional[Callable[[str], None]]


@dataclass
class Result:
    track: str                          # cleaned track name
    out_dir: Path                       # folder containing the stems
    stems: Dict[str, Path] = field(default_factory=dict)
    archive: Optional[Path] = None      # zip path, if bundling was requested

    @property
    def stem_names(self):
        return list(self.stems)


def separate(
    source: str,
    *,
    out_dir: str | Path = "stems",
    model: str = DEFAULT_MODEL,
    two_stems: Optional[str] = None,
    fmt: str = "wav",
    mp3_bitrate: int = 320,
    zip_output: bool = False,
    device: Optional[str] = None,
    on_event: EventHook = None,
    on_progress: Optional[Callable[[float], None]] = None,
) -> Result:
    """Separate ``source`` (a local audio file or, with the ``url`` extra, a URL)
    into stems written under ``out_dir/<track name>/``.

    This is the single function the CLI and library users call.
    """
    out_root = Path(out_dir).expanduser()

    # One temp dir for any URL download; cleaned up on exit no matter what.
    with tempfile.TemporaryDirectory(prefix="chuja-") as tmp:
        resolved = sources.resolve(source, workdir=Path(tmp), on_event=on_event)

        samplerate, stems = separator.separate(
            resolved.path,
            model=model,
            device=device,
            two_stems=two_stems,
            on_event=on_event,
            on_progress=on_progress,
        )

        track_dir = unique_dir(out_root, safe_name(resolved.title))
        if on_event:
            on_event(f"Writing {len(stems)} stems to {track_dir}")

        written = export.write_stems(
            stems, samplerate, track_dir, fmt=fmt, mp3_bitrate=mp3_bitrate
        )

        archive = None
        if zip_output:
            # NB: not track_dir.with_suffix(".zip") — a track title like
            # "feat. K.Flay" would have ".Flay" mistaken for an extension.
            archive = export.bundle(written, track_dir.parent / f"{track_dir.name}.zip")
            if on_event:
                on_event(f"Bundled archive at {archive}")

    return Result(track=resolved.title, out_dir=track_dir, stems=written, archive=archive)
