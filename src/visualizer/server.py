"""Local-only HTTP server for the visualizer -- serves the HUD page at `/`
and a Server-Sent Events stream of state.py's published events at
`/events`. Bound to 127.0.0.1 only, never the network. Plain stdlib
http.server + a browser's built-in EventSource -- no new dependency,
unlike a real WebSocket server would need."""

from __future__ import annotations

import json
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

from visualizer import state

_PAGE_PATH = Path(__file__).resolve().parent / "page.html"

# How often to send an SSE comment line (": keepalive") while nothing new
# is published -- without this, a closed browser tab's connection thread
# would sit blocked on q.get() forever instead of noticing the socket died.
_KEEPALIVE_SECONDS = 15

_server: ThreadingHTTPServer | None = None
_server_lock = threading.Lock()

# The HUD's own on/off button (POST /api/toggle) -- registered by
# menubar.py at startup, since this module has no business knowing about
# VoiceLoopController/rumps itself (same layering as state.py's own
# publish/subscribe: this module only ever reacts to what it's told).
# None (the default) means the visualizer is running standalone, without
# the menu bar app driving it -- the endpoint reports that plainly instead
# of pretending the click did something.
_toggle_callback: Callable[[], None] | None = None


def set_toggle_callback(callback: Callable[[], None] | None) -> None:
    global _toggle_callback
    _toggle_callback = callback


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A002 -- stdlib signature
        pass  # quiet -- runs as a background thread inside a GUI app

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._serve_page()
        elif self.path == "/events":
            self._serve_events()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/api/toggle":
            self._handle_toggle()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_toggle(self) -> None:
        if _toggle_callback is None:
            self.send_response(503)
            self.end_headers()
            return
        # Runs on this request's own thread, never the main/AppKit one --
        # see menubar.py's own registered callback for how it hops back
        # before touching anything NSStatusItem-related.
        _toggle_callback()
        self.send_response(204)
        self.end_headers()

    def _serve_page(self) -> None:
        body = _PAGE_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        q = state.subscribe()
        try:
            self._write_event(state.current())  # so a new tab isn't blank until the next transition
            data_event = state.current_data()
            if data_event is not None:
                self._write_event(data_event)  # likewise for whatever chart was last shown
            while True:
                try:
                    event = q.get(timeout=_KEEPALIVE_SECONDS)
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
                    continue
                self._write_event(event)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass  # tab closed -- nothing to clean up beyond the finally below
        finally:
            state.unsubscribe(q)

    def _write_event(self, event: state.StateEvent | state.DataEvent) -> None:
        if isinstance(event, state.DataEvent):
            body = {"type": "data", "kind": event.kind, "payload": event.payload}
        else:
            body = {"type": "state", "state": event.state, "text": event.text}
        self.wfile.write(f"data: {json.dumps(body)}\n\n".encode("utf-8"))
        self.wfile.flush()


def start(port: int = 8765) -> int:
    """Starts the server at most once per process -- calling again just
    returns the already-running port, so the menu bar button is safe to
    click repeatedly without ever hitting "address already in use"."""
    global _server
    with _server_lock:
        if _server is not None:
            return _server.server_address[1]
        server = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
        threading.Thread(target=server.serve_forever, daemon=True, name="jarvis-visualizer-http").start()
        _server = server
        return server.server_address[1]


def url() -> str:
    return f"http://127.0.0.1:{start()}/"
