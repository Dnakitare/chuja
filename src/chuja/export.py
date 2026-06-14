"""Write separated stem tensors to disk and optionally bundle them.

Export is intentionally backend-independent: WAV/FLAC go through soundfile
(libsndfile) and MP3 through ffmpeg. We deliberately do NOT use torchaudio's
save path, which depends on whichever audio backend (sox/soundfile/torchcodec)
happens to be installed and fails confusingly across environments.
"""

from __future__ import annotations

import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Dict

from .errors import ExportError
from .util import require_ffmpeg

FORMATS = {"wav", "mp3", "flac"}


def write_stems(
    stems: Dict,
    samplerate: int,
    out_dir: Path,
    *,
    fmt: str = "wav",
    mp3_bitrate: int = 320,
) -> Dict[str, Path]:
    """Write each stem tensor to ``out_dir/<name>.<fmt>``.

    Returns a mapping of stem name -> written path."""
    if fmt not in FORMATS:
        raise ExportError(f"Unsupported format '{fmt}'. Choose from: {', '.join(sorted(FORMATS))}.")

    out_dir.mkdir(parents=True, exist_ok=True)
    written: Dict[str, Path] = {}
    for name, tensor in stems.items():
        dest = out_dir / f"{name}.{fmt}"
        try:
            _write_one(tensor, samplerate, dest, fmt=fmt, mp3_bitrate=mp3_bitrate)
        except ExportError:
            raise
        except Exception as exc:
            raise ExportError(f"Failed to write stem '{name}' to {dest}: {exc}") from exc
        written[name] = dest
    return written


def _to_frames(tensor):
    """Convert a Demucs stem tensor [channels, time] to a soundfile-shaped
    float32 array [time, channels], rescaling if it would clip."""
    import numpy as np

    data = tensor.detach().to("cpu").numpy()  # [channels, time]
    if data.ndim == 1:
        data = data[None, :]
    peak = float(np.abs(data).max()) if data.size else 0.0
    if peak > 1.0:  # match Demucs' default 'rescale' clip behavior
        data = data / peak
    return np.ascontiguousarray(data.T, dtype="float32")  # [time, channels]


def _write_one(tensor, samplerate: int, dest: Path, *, fmt: str, mp3_bitrate: int) -> None:
    try:
        import soundfile as sf
    except ImportError as exc:  # pragma: no cover - import guard
        raise ExportError(
            "soundfile is required for audio export. Install chuja's deps: pip install chuja"
        ) from exc

    frames = _to_frames(tensor)

    if fmt == "wav":
        sf.write(str(dest), frames, samplerate, subtype="PCM_16")
    elif fmt == "flac":
        sf.write(str(dest), frames, samplerate, format="FLAC")
    elif fmt == "mp3":
        _write_mp3(frames, samplerate, dest, mp3_bitrate, sf)
    else:  # pragma: no cover - guarded by caller
        raise ExportError(f"Unsupported format '{fmt}'.")


def _write_mp3(frames, samplerate: int, dest: Path, bitrate: int, sf) -> None:
    """Encode to MP3 via ffmpeg (libsndfile can't write MP3)."""
    ffmpeg = require_ffmpeg()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        sf.write(str(tmp_path), frames, samplerate, subtype="PCM_16")
        proc = subprocess.run(
            [ffmpeg, "-y", "-loglevel", "error", "-i", str(tmp_path),
             "-b:a", f"{bitrate}k", str(dest)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise ExportError(f"ffmpeg failed to encode MP3: {proc.stderr.strip()}")
    finally:
        tmp_path.unlink(missing_ok=True)


def bundle(stem_paths: Dict[str, Path], archive_path: Path) -> Path:
    """Zip the written stems into a single portable archive."""
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in stem_paths.values():
                zf.write(path, arcname=path.name)
    except OSError as exc:
        raise ExportError(f"Failed to build archive {archive_path}: {exc}") from exc
    return archive_path
