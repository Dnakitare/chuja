from pathlib import Path

import pytest

from chuja.util import is_url, safe_name, unique_dir


@pytest.mark.parametrize(
    "value,expected",
    [
        ("https://youtube.com/watch?v=abc", True),
        ("http://soundcloud.com/x/y", True),
        ("song.mp3", False),
        ("/Users/me/song.mp3", False),
        ("~/music/track.flac", False),
        ("ftp://example.com/a.mp3", False),
        ("https://", False),
        ("", False),
    ],
)
def test_is_url(value, expected):
    assert is_url(value) is expected


def test_safe_name_strips_unsafe_chars():
    assert safe_name('AC/DC: Back\\In*Black?') == "AC DC Back In Black"


def test_safe_name_collapses_whitespace_and_trims_dots():
    assert safe_name("  hello   world ...  ") == "hello world"


def test_safe_name_falls_back_when_empty():
    assert safe_name("///", fallback="track") == "track"
    assert safe_name("", fallback="x") == "x"


def test_safe_name_truncates():
    assert len(safe_name("a" * 500, max_len=120)) == 120


def test_unique_dir_avoids_collisions(tmp_path: Path):
    first = unique_dir(tmp_path, "song")
    first.mkdir()
    second = unique_dir(tmp_path, "song")
    assert second.name == "song-2"
    second.mkdir()
    assert unique_dir(tmp_path, "song").name == "song-3"
