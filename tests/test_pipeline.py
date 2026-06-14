from pathlib import Path

from chuja import pipeline
from chuja.sources import ResolvedSource


def _patch(monkeypatch, *, title="My Track", written=None, two_stems_seen=None):
    """Replace the heavy stages with light fakes and record what they receive."""
    calls = {}

    def fake_resolve(source, *, workdir, on_event=None):
        calls["source"] = source
        return ResolvedSource(path=Path("/tmp/in.wav"), title=title, is_temporary=False)

    def fake_separate(path, *, model, device, two_stems, on_event=None, on_progress=None):
        calls["model"] = model
        calls["two_stems"] = two_stems
        if on_progress:
            on_progress(0.5)
            on_progress(1.0)
        return 44100, {"vocals": object(), "accompaniment": object()}

    def fake_write(stems, samplerate, out_dir, *, fmt, mp3_bitrate):
        calls["out_dir"] = out_dir
        calls["fmt"] = fmt
        out_dir.mkdir(parents=True, exist_ok=True)
        return {name: out_dir / f"{name}.{fmt}" for name in stems}

    def fake_bundle(stem_paths, archive_path):
        calls["archive"] = archive_path
        return archive_path

    monkeypatch.setattr(pipeline.sources, "resolve", fake_resolve)
    monkeypatch.setattr(pipeline.separator, "separate", fake_separate)
    monkeypatch.setattr(pipeline.export, "write_stems", fake_write)
    monkeypatch.setattr(pipeline.export, "bundle", fake_bundle)
    return calls


def test_pipeline_happy_path(tmp_path, monkeypatch):
    calls = _patch(monkeypatch)
    result = pipeline.separate("song.mp3", out_dir=tmp_path, fmt="mp3")

    assert result.track == "My Track"
    assert result.out_dir == tmp_path / "My Track"
    assert set(result.stem_names) == {"vocals", "accompaniment"}
    assert result.archive is None
    assert calls["fmt"] == "mp3"


def test_pipeline_passes_two_stems_through(tmp_path, monkeypatch):
    calls = _patch(monkeypatch)
    pipeline.separate("song.mp3", out_dir=tmp_path, two_stems="vocals")
    assert calls["two_stems"] == "vocals"


def test_pipeline_zip(tmp_path, monkeypatch):
    _patch(monkeypatch)
    result = pipeline.separate("song.mp3", out_dir=tmp_path, zip_output=True)
    assert result.archive == (tmp_path / "My Track").with_suffix(".zip")


def test_pipeline_sanitizes_track_name(tmp_path, monkeypatch):
    _patch(monkeypatch, title="AC/DC: Hells Bells")
    result = pipeline.separate("song.mp3", out_dir=tmp_path)
    # Folder name must be filesystem-safe even though .track keeps the raw title.
    assert "/" not in result.out_dir.name
    assert result.out_dir.parent == tmp_path
