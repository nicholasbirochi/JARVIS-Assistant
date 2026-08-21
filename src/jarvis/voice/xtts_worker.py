"""Runs XTTS-v2 synthesis in its own OS process, isolated from the main
JARVIS process. See xtts_engine.py's module docstring for why this can't
run in-process with the wake-word listener: loading torchcodec's FFmpeg
in the same process that already has faster-whisper's own bundled FFmpeg
(via PyAV) loaded caused a real ObjC class collision that silently broke
microphone capture. Running here instead means that risk, if it recurs at
all, stays contained to this throwaway process -- it never touches
PvRecorder.

Started as a subprocess by xtts_client.py
(`python -m jarvis.voice.xtts_worker`) -- never run directly. Talks HTTP,
127.0.0.1 only, plain stdlib -- same pattern as
jarvis/visualizer/server.py, no new dependency.
"""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jarvis.voice import xtts_engine


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
        pass  # quiet -- runs headless as a subprocess, its own log file captures prints below

    def do_GET(self) -> None:
        if self.path == "/health":
            self._respond_json(200, {"ready": xtts_engine.is_ready()})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/synthesize":
            self._handle_synthesize()
        elif self.path == "/synthesize_stream":
            self._handle_synthesize_stream()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_synthesize(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length))
            text = body["text"]
        except (json.JSONDecodeError, KeyError) as exc:
            self._respond_json(400, {"error": f"corpo inválido: {exc}"})
            return

        if not xtts_engine.is_ready():
            self._respond_json(503, {"error": "modelo ainda não carregado"})
            return

        fd, out_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            xtts_engine.synthesize_to_file(text, out_path)
            with open(out_path, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            self._respond_json(500, {"error": str(exc)})
        finally:
            os.unlink(out_path)

    def _handle_synthesize_stream(self) -> None:
        """Streams raw PCM chunks as XTTS generates them, instead of
        waiting for the whole utterance (see xtts_engine.synthesize_stream's
        docstring for why) -- so playback (jarvis/voice/tts.py, via ffplay)
        can start almost immediately instead of after several seconds of
        silence. Framing: each chunk is a 4-byte big-endian length prefix
        followed by that many raw PCM bytes; a zero-length chunk marks a
        clean end. Deliberately not real HTTP chunked transfer-encoding --
        this is a length-prefixed protocol we fully control on both ends
        (see xtts_client.py), simpler to get right than hand-rolling
        chunked-encoding framing for a single, local, internal endpoint."""
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length))
            text = body["text"]
        except (json.JSONDecodeError, KeyError) as exc:
            self._respond_json(400, {"error": f"corpo inválido: {exc}"})
            return

        if not xtts_engine.is_ready():
            self._respond_json(503, {"error": "modelo ainda não carregado"})
            return

        # Fetch the first chunk BEFORE sending any response headers -- a
        # failure here can still become a clean 500 JSON error, same
        # contract as /synthesize. A failure AFTER this point means audio
        # may already be playing on the client, so it just ends the
        # stream early instead (see the except below).
        chunk_iter = xtts_engine.synthesize_stream(text)
        try:
            first_chunk = next(chunk_iter)
            got_first_chunk = True
        except StopIteration:
            got_first_chunk = False
        except Exception as exc:
            self._respond_json(500, {"error": str(exc)})
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.end_headers()
        try:
            if got_first_chunk:
                self._write_chunk(first_chunk)
                for chunk in chunk_iter:
                    self._write_chunk(chunk)
            self._write_chunk(b"")  # terminator -- signals a clean end
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # client disconnected (e.g. interrupted mid-speech) -- nothing more to do

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(struct.pack(">I", len(data)))
        if data:
            self.wfile.write(data)

    def _respond_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    from jarvis.config import XTTS_WORKER_PORT

    server = ThreadingHTTPServer(("127.0.0.1", XTTS_WORKER_PORT), _Handler)
    print(f"[xtts_worker] pid={os.getpid()} listening on 127.0.0.1:{XTTS_WORKER_PORT}", flush=True)
    print("[xtts_worker] loading model...", flush=True)
    xtts_engine.preload_in_background()
    server.serve_forever()


if __name__ == "__main__":
    main()
