import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import config
from voice import xtts_engine
from voice import xtts_client


class FakePopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self._returncode = None

    def poll(self):
        return self._returncode

    def finish(self, code=0):
        self._returncode = code


@pytest.fixture(autouse=True)
def _reset(monkeypatch, tmp_path):
    monkeypatch.setattr(xtts_client, "_process", None)
    monkeypatch.setattr(xtts_client, "_log_file", None)
    monkeypatch.setattr(config, "LOCAL_STATE_DIR", tmp_path)


def test_has_reference_audio_delegates_to_engine(monkeypatch):
    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: True)
    assert xtts_client.has_reference_audio() is True

    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: False)
    assert xtts_client.has_reference_audio() is False


def test_ensure_worker_started_noop_without_reference_audio(monkeypatch):
    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: False)
    calls = []
    monkeypatch.setattr(xtts_client.subprocess, "Popen", lambda *a, **kw: calls.append(1) or FakePopen(a, **kw))

    xtts_client.ensure_worker_started()

    assert calls == []


def test_ensure_worker_started_spawns_subprocess(monkeypatch):
    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: True)
    created = []
    monkeypatch.setattr(
        xtts_client.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1]
    )
    monkeypatch.setattr(xtts_client.atexit, "register", lambda fn: None)

    xtts_client.ensure_worker_started()

    assert len(created) == 1
    assert "voice.xtts_worker" in created[0].args
    # Real regression: sys.executable doesn't reliably mean "a python that
    # can import voice.xtts_worker" -- under the packaged JARVIS.app
    # (py2app alias mode) it resolves to the raw Homebrew framework
    # interpreter, with no awareness of this project's venv, and the
    # worker died every time with ModuleNotFoundError. Must always be the
    # project's own venv python explicitly, regardless of how this
    # process itself was launched (not asserting sys.executable is absent
    # here -- in a
    # normal venv-run test session the two paths happen to coincide).
    assert str(config.PROJECT_ROOT / ".venv" / "bin" / "python") in created[0].args
    assert created[0].kwargs.get("cwd") == config.PROJECT_ROOT / "src"


def test_ensure_worker_started_does_not_relaunch_while_running(monkeypatch):
    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: True)
    created = []
    monkeypatch.setattr(
        xtts_client.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1]
    )
    monkeypatch.setattr(xtts_client.atexit, "register", lambda fn: None)

    xtts_client.ensure_worker_started()
    xtts_client.ensure_worker_started()

    assert len(created) == 1


def test_ensure_worker_started_relaunches_after_worker_exited(monkeypatch):
    monkeypatch.setattr(xtts_engine, "has_reference_audio", lambda: True)
    created = []
    monkeypatch.setattr(
        xtts_client.subprocess, "Popen", lambda args, **kw: created.append(FakePopen(args, **kw)) or created[-1]
    )
    monkeypatch.setattr(xtts_client.atexit, "register", lambda fn: None)

    xtts_client.ensure_worker_started()
    created[0].finish()
    xtts_client.ensure_worker_started()

    assert len(created) == 2


def test_is_ready_false_when_worker_unreachable(monkeypatch):
    monkeypatch.setattr(config, "XTTS_WORKER_PORT", 1)  # nothing listens on port 1

    assert xtts_client.is_ready() is False


# ---- against a real (fake-handler) HTTP server ----


class _FakeWorkerHandler(BaseHTTPRequestHandler):
    ready = True
    synth_bytes = b"RIFFfakewav"
    synth_status = 200
    stream_chunks: list[bytes] = [b"chunk1", b"chunk2"]
    stream_status = 200

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"ready": self.ready}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.path == "/synthesize_stream":
            self._handle_synthesize_stream()
            return
        if self.synth_status != 200:
            body = json.dumps({"error": "boom"}).encode()
            self.send_response(self.synth_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(self.synth_bytes)))
        self.end_headers()
        self.wfile.write(self.synth_bytes)

    def _handle_synthesize_stream(self):
        import struct

        if self.stream_status != 200:
            body = json.dumps({"error": "boom"}).encode()
            self.send_response(self.stream_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        for chunk in self.stream_chunks:
            self.wfile.write(struct.pack(">I", len(chunk)))
            self.wfile.write(chunk)
        self.wfile.write(struct.pack(">I", 0))


@pytest.fixture()
def fake_worker(monkeypatch):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeWorkerHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(config, "XTTS_WORKER_PORT", server.server_address[1])
    try:
        yield
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_is_ready_reflects_real_health_response(fake_worker):
    _FakeWorkerHandler.ready = True
    assert xtts_client.is_ready() is True

    _FakeWorkerHandler.ready = False
    assert xtts_client.is_ready() is False


def test_synthesize_to_file_writes_response_bytes(fake_worker, tmp_path):
    _FakeWorkerHandler.synth_status = 200
    _FakeWorkerHandler.synth_bytes = b"RIFFrealenoughwavbytes"
    out_path = tmp_path / "out.wav"

    xtts_client.synthesize_to_file("olá", str(out_path))

    assert out_path.read_bytes() == b"RIFFrealenoughwavbytes"


def test_synthesize_to_file_raises_on_worker_error(fake_worker, tmp_path):
    _FakeWorkerHandler.synth_status = 500
    out_path = tmp_path / "out.wav"

    with pytest.raises(urllib.error.HTTPError):
        xtts_client.synthesize_to_file("olá", str(out_path))


def test_synthesize_stream_yields_chunks_in_order(fake_worker):
    _FakeWorkerHandler.stream_status = 200
    _FakeWorkerHandler.stream_chunks = [b"chunk1", b"chunkTWO"]

    assert list(xtts_client.synthesize_stream("olá")) == [b"chunk1", b"chunkTWO"]


def test_synthesize_stream_empty_stream_yields_nothing(fake_worker):
    _FakeWorkerHandler.stream_status = 200
    _FakeWorkerHandler.stream_chunks = []

    assert list(xtts_client.synthesize_stream("")) == []


def test_synthesize_stream_raises_on_worker_error_before_any_chunk(fake_worker):
    _FakeWorkerHandler.stream_status = 500

    with pytest.raises(urllib.error.HTTPError):
        list(xtts_client.synthesize_stream("olá"))
