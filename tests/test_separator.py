import pytest

from chuja import errors
from chuja.separator import MODELS, _collapse_to_two, separate


class FakeTensor:
    """Minimal stand-in for a torch tensor supporting clone() and +."""

    def __init__(self, value):
        self.value = value

    def clone(self):
        return FakeTensor(self.value)

    def __add__(self, other):
        return FakeTensor(self.value + other.value)


def test_collapse_to_two_sums_others():
    stems = {
        "drums": FakeTensor(1),
        "bass": FakeTensor(2),
        "other": FakeTensor(3),
        "vocals": FakeTensor(10),
    }
    out = _collapse_to_two(stems, keep="vocals")
    assert set(out) == {"vocals", "accompaniment"}
    assert out["vocals"].value == 10
    assert out["accompaniment"].value == 6  # 1 + 2 + 3


def test_collapse_to_two_unknown_stem():
    with pytest.raises(errors.SeparationError, match="Cannot isolate"):
        _collapse_to_two({"vocals": FakeTensor(1)}, keep="piano")


def test_separate_rejects_unknown_model(tmp_path):
    with pytest.raises(errors.SeparationError, match="Unknown model"):
        separate(tmp_path / "x.wav", model="not-a-real-model")


def test_default_model_is_listed():
    assert "htdemucs" in MODELS


def test_progress_iter_reports_monotonic_fractions():
    from chuja.separator import _ProgressIter

    seen = []
    items = ["a", "b", "c", "d"]
    out = list(_ProgressIter(items, seen.append))
    assert out == items                       # passes items through unchanged
    assert seen == [0.0, 0.25, 0.5, 0.75, 1.0]  # 0 at start, 1.0 at completion


def test_progress_iter_tolerates_no_callback():
    from chuja.separator import _ProgressIter

    assert list(_ProgressIter([1, 2, 3], None)) == [1, 2, 3]


def test_weights_cached_detection(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")  # skip if the ML stack isn't installed
    from chuja.separator import _weights_cached

    monkeypatch.setattr(torch.hub, "get_dir", lambda: str(tmp_path))
    assert _weights_cached() is False                       # no checkpoints dir yet
    ckpt = tmp_path / "checkpoints"
    ckpt.mkdir()
    assert _weights_cached() is False                       # dir exists but empty
    (ckpt / "abc123.th").write_bytes(b"weights")
    assert _weights_cached() is True                        # a cached model is present
