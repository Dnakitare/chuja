"""Local web server backing `chuja serve` — the browser mixing console.

Deliberately stdlib-only (no FastAPI/uvicorn): a ThreadingHTTPServer with a
tiny JSON API and a single static HTML page. File uploads are sent as the raw
request body (filename in a header) so we never need multipart parsing.

Binds to localhost by design — it runs separation on whatever file/URL it is
given, which should never be exposed to a network.
"""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from . import pipeline
from .errors import ChujaError
from .util import is_url

HERE = Path(__file__).parent
CONSOLE_HTML = HERE / "web" / "console.html"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".mp3": "audio/mpeg", ".wav": "audio/wav", ".flac": "audio/flac",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg", ".opus": "audio/ogg",
    ".zip": "application/zip",
}


@dataclass
class Job:
    id: str
    status: str = "queued"        # queued|fetching|separating|exporting|done|error
    phase: str = ""               # fetching|separating|exporting (for the UI steps)
    message: str = "queued"
    track: str = ""
    progress: float = 0.0         # 0..1 within the separation phase
    stems: List[dict] = field(default_factory=list)
    archive_url: Optional[str] = None
    error: Optional[str] = None

    def public(self) -> dict:
        return {
            "id": self.id, "status": self.status, "phase": self.phase,
            "message": self.message, "track": self.track, "progress": self.progress,
            "stems": self.stems, "archive_url": self.archive_url, "error": self.error,
        }


def _infer_phase(msg: str) -> str:
    m = msg.lower()
    if "fetch" in m:
        return "fetching"
    if "separat" in m or "loading model" in m:
        return "separating"
    if "writing" in m or "bundl" in m:
        return "exporting"
    return ""


class Store:
    """Holds jobs + the output directory. Shared by all request handlers."""

    def __init__(self, out_root: Path, model: str):
        self.out_root = out_root.resolve()
        self.model = model
        self.jobs: Dict[str, Job] = {}
        self.lock = threading.Lock()
        (self.out_root / "_uploads").mkdir(parents=True, exist_ok=True)

    def create(self) -> Job:
        job = Job(id=uuid.uuid4().hex[:12])
        with self.lock:
            self.jobs[job.id] = job
        return job

    def start(self, job: Job, source: str, *, model: str, fmt: str, two_stems: Optional[str]):
        t = threading.Thread(
            target=self._run, args=(job, source, model, fmt, two_stems), daemon=True
        )
        t.start()

    def _run(self, job, source, model, fmt, two_stems):
        def on_event(msg: str):
            job.message = msg
            ph = _infer_phase(msg)
            if ph:
                job.phase = ph
                job.status = ph

        def on_progress(frac: float):
            job.progress = frac

        job.status = "fetching" if is_url(source) else "separating"
        job.phase = job.status
        try:
            result = pipeline.separate(
                source, out_dir=self.out_root, model=model,
                two_stems=two_stems or None, fmt=fmt, zip_output=True,
                on_event=on_event, on_progress=on_progress,
            )
        except ChujaError as exc:
            job.status, job.error = "error", str(exc)
            return
        except Exception as exc:  # never let a worker thread die silently
            job.status, job.error = "error", f"unexpected error: {exc}"
            return

        rel = result.out_dir.relative_to(self.out_root).as_posix()
        job.track = result.track
        job.stems = [
            {"name": name, "url": f"/files/{quote(rel)}/{quote(path.name)}"}
            for name, path in result.stems.items()
        ]
        if result.archive:
            arel = result.archive.relative_to(self.out_root).as_posix()
            job.archive_url = f"/files/{quote(arel)}"
        job.status, job.phase = "done", "exporting"
        job.message = f"{len(result.stems)} stems ready"


def _make_handler(store: Store):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep the console quiet
            pass

        # -- helpers --
        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bytes(self, data: bytes, ctype: str, code=200, download_name=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Accept-Ranges", "none")
            if download_name:
                self.send_header("Content-Disposition", f'attachment; filename="{download_name}"')
            self.end_headers()
            self.wfile.write(data)

        # -- routing --
        def do_GET(self):
            path = unquote(self.path.split("?", 1)[0])
            if path == "/" or path == "/index.html":
                return self._serve_console()
            if path.startswith("/api/jobs/"):
                return self._job_status(path.rsplit("/", 1)[-1])
            if path.startswith("/files/"):
                return self._serve_file(path[len("/files/"):])
            self._json({"error": "not found"}, 404)

        def do_POST(self):
            if self.path.split("?", 1)[0] != "/api/jobs":
                return self._json({"error": "not found"}, 404)
            try:
                self._create_job()
            except Exception as exc:
                self._json({"error": str(exc)}, 400)

        # -- handlers --
        def _serve_console(self):
            try:
                html = CONSOLE_HTML.read_bytes()
            except OSError:
                return self._json({"error": "UI asset missing"}, 500)
            self._bytes(html, _CONTENT_TYPES[".html"])

        def _job_status(self, job_id):
            job = store.jobs.get(job_id)
            if not job:
                return self._json({"error": "unknown job"}, 404)
            self._json(job.public())

        def _serve_file(self, rel):
            target = (store.out_root / rel).resolve()
            # prevent path traversal outside the output root
            if not str(target).startswith(str(store.out_root)) or not target.is_file():
                return self._json({"error": "not found"}, 404)
            ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
            name = target.name if target.suffix.lower() == ".zip" else None
            self._bytes(target.read_bytes(), ctype, download_name=name)

        def _create_job(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            ctype = (self.headers.get("Content-Type") or "").lower()

            if ctype.startswith("application/json"):
                data = json.loads(body or b"{}")
                source = (data.get("url") or "").strip()
                if not source:
                    return self._json({"error": "no url provided"}, 400)
                model = data.get("model") or store.model
                fmt = data.get("format") or "mp3"
                two = data.get("two_stems") or None
            else:
                filename = unquote(self.headers.get("X-Chuja-Filename", "upload"))
                if not body:
                    return self._json({"error": "empty upload"}, 400)
                safe = Path(filename).name or "upload"
                # Keep the original filename intact (so the track name is clean)
                # by isolating each upload in its own subdir instead of prefixing.
                updir = store.out_root / "_uploads" / uuid.uuid4().hex[:8]
                updir.mkdir(parents=True, exist_ok=True)
                dest = updir / safe
                dest.write_bytes(body)
                source = str(dest)
                model = self.headers.get("X-Chuja-Model") or store.model
                fmt = self.headers.get("X-Chuja-Format") or "mp3"
                two = self.headers.get("X-Chuja-Two-Stems") or None

            job = store.create()
            store.start(job, source, model=model, fmt=fmt, two_stems=two)
            self._json({"id": job.id})

    return Handler


def serve(
    *,
    out_dir: Path,
    host: str = "127.0.0.1",
    port: int = 7777,
    model: str = "htdemucs",
):
    """Build and return a (server, url) pair. Caller runs serve_forever()."""
    store = Store(Path(out_dir), model)
    httpd = ThreadingHTTPServer((host, port), _make_handler(store))
    url = f"http://{host}:{httpd.server_address[1]}"
    return httpd, url
