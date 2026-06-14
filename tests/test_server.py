"""HTTP-level tests for the console server. pipeline.separate is faked so the
suite needs no torch/demucs — we're testing routing, the job lifecycle, file
serving, and path-traversal protection."""

import json
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

import pytest

from chuja import pipeline, server


def _fake_separate_factory():
    def fake_separate(source, *, out_dir, model, two_stems, fmt, zip_output, on_event=None, on_progress=None):
        on_event and on_event(f"Fetching audio from {source}")
        on_event and on_event("Separating stems (this is the slow part)")
        on_progress and on_progress(0.5)
        on_progress and on_progress(1.0)
        track_dir = Path(out_dir) / "Fake Track"
        track_dir.mkdir(parents=True, exist_ok=True)
        names = ["vocals", "accompaniment"] if two_stems else ["drums", "bass", "other", "vocals"]
        stems = {}
        for n in names:
            p = track_dir / f"{n}.{fmt}"
            p.write_bytes(b"RIFF-fake-" + n.encode())
            stems[n] = p
        archive = None
        if zip_output:
            archive = track_dir.parent / "Fake Track.zip"
            archive.write_bytes(b"PK-fake")
        on_event and on_event(f"Writing {len(stems)} stems to {track_dir}")
        return pipeline.Result(track="Fake Track", out_dir=track_dir, stems=stems, archive=archive)
    return fake_separate


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    monkeypatch.setattr(server.pipeline, "separate", _fake_separate_factory())
    httpd, url = server.serve(out_dir=tmp_path, host="127.0.0.1", port=0)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield url
    httpd.shutdown()
    httpd.server_close()


def _get(url, code=200):
    try:
        with urllib.request.urlopen(url) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post_json(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_index_serves_console_html(live_server):
    status, body = _get(live_server + "/")
    assert status == 200
    assert b"stem console" in body.lower() or b"chuja" in body.lower()


def test_full_job_lifecycle_via_url(live_server):
    job = _post_json(live_server + "/api/jobs", {"url": "https://example.com/x", "format": "mp3"})
    assert "id" in job

    # poll to completion
    final = None
    for _ in range(50):
        _, body = _get(f"{live_server}/api/jobs/{job['id']}")
        final = json.loads(body)
        if final["status"] in ("done", "error"):
            break
        time.sleep(0.05)

    assert final["status"] == "done", final
    assert final["track"] == "Fake Track"
    assert len(final["stems"]) == 4
    assert final["archive_url"]

    # stems are downloadable
    status, audio = _get(live_server + final["stems"][0]["url"])
    assert status == 200 and audio.startswith(b"RIFF-fake-")


def test_file_upload_via_raw_body(live_server):
    req = urllib.request.Request(
        live_server + "/api/jobs", data=b"fake-audio-bytes",
        headers={"X-Chuja-Filename": "My%20Song.mp3", "X-Chuja-Format": "wav",
                 "X-Chuja-Two-Stems": "vocals"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        job = json.loads(r.read())

    final = None
    for _ in range(50):
        _, body = _get(f"{live_server}/api/jobs/{job['id']}")
        final = json.loads(body)
        if final["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert final["status"] == "done"
    assert len(final["stems"]) == 2  # two-stems path


def test_unknown_job_404(live_server):
    status, _ = _get(live_server + "/api/jobs/deadbeef")
    assert status == 404


def test_path_traversal_blocked(live_server):
    status, _ = _get(live_server + "/files/../../../etc/passwd")
    assert status == 404
