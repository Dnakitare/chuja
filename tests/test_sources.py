import builtins

import pytest

from chuja import errors
from chuja import sources


def test_resolve_local_missing_file(tmp_path):
    with pytest.raises(errors.SourceError, match="not found"):
        sources.resolve(str(tmp_path / "nope.mp3"), workdir=tmp_path)


def test_resolve_local_directory(tmp_path):
    with pytest.raises(errors.SourceError, match="directory"):
        sources.resolve(str(tmp_path), workdir=tmp_path)


def test_resolve_local_unsupported_suffix(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hi")
    with pytest.raises(errors.SourceError, match="Unsupported file type"):
        sources.resolve(str(bad), workdir=tmp_path)


def test_resolve_local_ok(tmp_path):
    song = tmp_path / "My Song.mp3"
    song.write_bytes(b"\x00")
    resolved = sources.resolve(str(song), workdir=tmp_path)
    assert resolved.path == song
    assert resolved.title == "My Song"
    assert resolved.is_temporary is False


def test_url_without_extra_raises_clear_error(tmp_path, monkeypatch):
    """If yt_dlp is not importable, a URL must produce an actionable message."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yt_dlp":
            raise ImportError("no yt_dlp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(errors.MissingDependencyError, match="chuja\\[url\\]"):
        sources.resolve("https://example.com/x", workdir=tmp_path)
