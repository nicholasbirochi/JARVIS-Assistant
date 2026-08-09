import json
import struct
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from jarvis.voice import xtts_engine, xtts_worker


@pytest.fixture()
def running_server(monkeypatch):
    """Real HTTP server (ephemeral port), xtts_engine mocked out so no
    real model is ever touched."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), xtts_worker._Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_health_reports_not_ready_by_default(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: False)

    with urllib.request.urlopen(f"{running_server}/health", timeout=5) as resp:
        assert json.loads(resp.read()) == {"ready": False}


def test_health_reports_ready_once_model_loaded(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)

    with urllib.request.urlopen(f"{running_server}/health", timeout=5) as resp:
        assert json.loads(resp.read()) == {"ready": True}


def test_synthesize_returns_503_when_not_ready(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: False)

    req = urllib.request.Request(
        f"{running_server}/synthesize", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 503


def test_synthesize_returns_wav_bytes_on_success(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)

    def fake_synthesize(text, out_path):
        with open(out_path, "wb") as f:
            f.write(b"RIFF....WAVEfakecontent")

    monkeypatch.setattr(xtts_engine, "synthesize_to_file", fake_synthesize)

    req = urllib.request.Request(
        f"{running_server}/synthesize", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.headers["Content-Type"] == "audio/wav"
        assert resp.read() == b"RIFF....WAVEfakecontent"


def test_synthesize_returns_500_with_error_when_synthesis_raises(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)

    def raising_synthesize(text, out_path):
        raise RuntimeError("boom")

    monkeypatch.setattr(xtts_engine, "synthesize_to_file", raising_synthesize)

    req = urllib.request.Request(
        f"{running_server}/synthesize", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 500
    assert json.loads(exc_info.value.read())["error"] == "boom"


def test_unknown_get_path_is_404(running_server):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(f"{running_server}/nope", timeout=5)
    assert exc_info.value.code == 404


def test_unknown_post_path_is_404(running_server):
    req = urllib.request.Request(f"{running_server}/nope", data=b"{}", method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 404


# ---- /synthesize_stream ----


def _read_all_chunks(resp) -> list[bytes]:
    """Mirrors xtts_client.py's own framing reader, kept independent here
    on purpose -- this test should fail if the worker's framing and the
    client's parsing ever drift apart, not pass by construction because
    they share one implementation."""
    chunks = []
    while True:
        header = resp.read(4)
        assert len(header) == 4
        (length,) = struct.unpack(">I", header)
        if length == 0:
            return chunks
        data = resp.read(length)
        assert len(data) == length
        chunks.append(data)


def test_synthesize_stream_returns_503_when_not_ready(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: False)

    req = urllib.request.Request(
        f"{running_server}/synthesize_stream", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 503


def test_synthesize_stream_streams_chunks_with_length_prefix_framing(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)
    monkeypatch.setattr(xtts_engine, "synthesize_stream", lambda text: iter([b"chunk1", b"chunkTWO"]))

    req = urllib.request.Request(
        f"{running_server}/synthesize_stream", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.headers["Content-Type"] == "application/octet-stream"
        assert _read_all_chunks(resp) == [b"chunk1", b"chunkTWO"]


def test_synthesize_stream_sends_just_a_terminator_for_an_empty_stream(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)
    monkeypatch.setattr(xtts_engine, "synthesize_stream", lambda text: iter([]))

    req = urllib.request.Request(
        f"{running_server}/synthesize_stream", data=json.dumps({"text": ""}).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert _read_all_chunks(resp) == []


def test_synthesize_stream_returns_500_when_it_fails_before_any_chunk(running_server, monkeypatch):
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)

    def raising_stream(text):
        raise RuntimeError("boom")
        yield  # pragma: no cover -- makes this a generator function

    monkeypatch.setattr(xtts_engine, "synthesize_stream", raising_stream)

    req = urllib.request.Request(
        f"{running_server}/synthesize_stream", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req, timeout=5)
    assert exc_info.value.code == 500
    assert json.loads(exc_info.value.read())["error"] == "boom"


def test_synthesize_stream_ends_stream_early_when_it_fails_mid_stream(running_server, monkeypatch):
    # Unlike a failure before the first chunk, a mid-stream failure can't
    # become a clean 500 anymore -- headers (200) are already sent. It
    # should just end the stream without a terminator instead of raising
    # out of the request handler.
    monkeypatch.setattr(xtts_engine, "is_ready", lambda: True)

    def failing_partway(text):
        yield b"chunk1"
        raise RuntimeError("boom partway through")

    monkeypatch.setattr(xtts_engine, "synthesize_stream", failing_partway)

    req = urllib.request.Request(
        f"{running_server}/synthesize_stream", data=json.dumps({"text": "olá"}).encode(), method="POST"
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        # First chunk's own length+data still arrive fine...
        header = resp.read(4)
        (length,) = struct.unpack(">I", header)
        assert length == 6
        assert resp.read(6) == b"chunk1"
        # ...but the connection ends without a terminator ever showing up.
        assert resp.read() == b""
