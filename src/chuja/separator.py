"""Thin wrapper around Demucs (Meta's source-separation model).

All torch/demucs imports are lazy so the rest of the package — and the test
suite — can run without the multi-gigabyte ML stack installed.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .errors import SeparationError

# Demucs drives its separation over audio chunks and shows a tqdm bar; it has no
# progress callback in 4.0.1. We patch the module-level `tqdm` it uses with the
# shim below to surface a real 0..1 fraction. The patch mutates a module global,
# so separations are serialized through this lock to keep it thread-safe.
_APPLY_LOCK = threading.Lock()


class _ProgressIter:
    """Wraps Demucs' chunk-futures iterator and reports completion fraction.

    Demucs uses a lazy DummyPoolExecutor (num_workers=0), so the heavy compute
    runs when each future is consumed in the loop body — i.e. between our
    yields — making the per-item count an accurate progress signal. For a
    multi-model bag (e.g. htdemucs_ft) the bar resets once per sub-model; the
    default htdemucs is a single pass and runs cleanly 0→100%."""

    def __init__(self, iterable, on_progress, **_ignored):
        self._items = list(iterable)
        self._total = len(self._items)
        self._on = on_progress

    def __iter__(self):
        if self._on:
            self._on(0.0)
        for i, item in enumerate(self._items, 1):
            yield item
            if self._on and self._total:
                self._on(min(1.0, i / self._total))


class _TqdmShim:
    """Stand-in for the `tqdm` module that Demucs imports, exposing just the
    `.tqdm(iterable, ...)` call site we need to intercept."""

    def __init__(self, on_progress):
        self._on = on_progress

    def tqdm(self, iterable=None, *args, **kwargs):
        return _ProgressIter(iterable, self._on, **kwargs)

# Models shipped with Demucs v4. htdemucs is the SOTA default; the _6s variant
# additionally splits piano and guitar out of "other".
MODELS = {
    "htdemucs": "Hybrid Transformer Demucs (default, 4 stems)",
    "htdemucs_ft": "Fine-tuned htdemucs — best quality, ~4x slower",
    "htdemucs_6s": "6 stems: adds piano + guitar (experimental)",
    "mdx_extra": "MDX challenge model, 4 stems",
}

DEFAULT_MODEL = "htdemucs"


def _weights_cached() -> bool:
    """True if any Demucs weights already sit in the torch hub cache.

    Used only to decide whether to warn about the one-time model download on a
    first run. Errs toward True so a detection failure never shows a false alarm."""
    try:
        import torch  # lazy

        ckpt = Path(torch.hub.get_dir()) / "checkpoints"
        return ckpt.is_dir() and any(ckpt.glob("*.th"))
    except Exception:
        return True


def pick_device(requested: Optional[str] = None) -> str:
    """Choose the fastest available torch device unless one is forced."""
    if requested:
        return requested
    import torch  # lazy

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"  # Apple Silicon
    return "cpu"


def separate(
    audio_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    device: Optional[str] = None,
    two_stems: Optional[str] = None,
    on_event: Optional[Callable[[str], None]] = None,
    on_progress: Optional[Callable[[float], None]] = None,
):
    """Run separation and return ``(samplerate, {stem_name: tensor})``.

    ``two_stems="vocals"`` collapses the result to just that stem plus an
    ``accompaniment`` track (the sum of everything else) — the classic
    karaoke / acapella split.
    """
    if model not in MODELS:
        raise SeparationError(
            f"Unknown model '{model}'. Available: {', '.join(MODELS)}."
        )

    try:
        import torch  # lazy
        from demucs.apply import apply_model
        from demucs.audio import AudioFile, convert_audio
        from demucs.pretrained import get_model
    except ImportError as exc:  # pragma: no cover - import guard
        raise SeparationError(
            "Demucs is not installed. Install chuja's core dependencies:\n"
            "  pip install chuja"
        ) from exc

    device = pick_device(device)
    if on_event:
        on_event(f"Loading model '{model}' on {device}")
        if not _weights_cached():
            # The first separation pulls model weights from the internet; without
            # this, the UI/CLI looks frozen during an otherwise-silent download.
            on_event(
                f"First run — downloading the '{model}' model (~80–150 MB). "
                "One time only, then it's cached."
            )

    try:
        net = get_model(model)
    except Exception as exc:
        raise SeparationError(f"Failed to load model '{model}': {exc}") from exc
    net.eval()

    # Decode to the model's native samplerate/channels without any lossy
    # re-encode, then normalize exactly as Demucs' own CLI does.
    try:
        wav = AudioFile(str(audio_path)).read(
            streams=0, samplerate=net.samplerate, channels=net.audio_channels
        )
        wav = convert_audio(wav, net.samplerate, net.samplerate, net.audio_channels)
    except Exception as exc:
        raise SeparationError(f"Could not decode audio at {audio_path}: {exc}") from exc

    ref = wav.mean(0)
    std = ref.std()
    if float(std) == 0.0:  # pure silence — avoid divide-by-zero
        std = torch.tensor(1.0)
    wav = (wav - ref.mean()) / std

    if on_event:
        on_event("Separating stems (this is the slow part)")

    # When a numeric progress hook is given, swap Demucs' tqdm for our shim so we
    # can report a real fraction (and stay silent). Otherwise leave the native
    # bar in place (the CLI relies on it). The lock guards the global patch.
    import demucs.apply as _dapply

    want_bar = bool(on_event or on_progress)
    try:
        with _APPLY_LOCK:
            original_tqdm = _dapply.tqdm
            if on_progress is not None:
                _dapply.tqdm = _TqdmShim(on_progress)
            try:
                with torch.no_grad():
                    out = apply_model(
                        net, wav[None], device=device, progress=want_bar, split=True
                    )[0]
            finally:
                _dapply.tqdm = original_tqdm
    except SeparationError:
        raise
    except Exception as exc:
        raise SeparationError(f"Separation failed: {exc}") from exc

    if on_progress is not None:
        on_progress(1.0)

    out = out * std + ref.mean()
    stems = {name: out[i] for i, name in enumerate(net.sources)}

    if two_stems is not None:
        stems = _collapse_to_two(stems, keep=two_stems)

    return net.samplerate, stems


def _collapse_to_two(stems: Dict, keep: str) -> Dict:
    """Reduce a full stem dict to {keep, 'accompaniment'} by summing the rest."""
    if keep not in stems:
        raise SeparationError(
            f"Cannot isolate '{keep}': model produced {list(stems)}."
        )
    others: List = [t for name, t in stems.items() if name != keep]
    accompaniment = others[0].clone()
    for t in others[1:]:
        accompaniment = accompaniment + t
    return {keep: stems[keep], "accompaniment": accompaniment}
