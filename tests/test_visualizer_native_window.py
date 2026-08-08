"""Only the pure-Python idempotency logic is covered here -- actually
creating an NSWindow/WKWebView is real Cocoa UI (verified manually, live,
via a screenshot: see the commit this file was added in) and isn't
unit-tested, matching jarvis/menubar.py's own JarvisMenuBarApp precedent
of leaving real AppKit object creation to manual/live verification."""

from jarvis.visualizer import native_window


class FakeWindow:
    def __init__(self):
        self.brought_forward = False

    def makeKeyAndOrderFront_(self, _sender):
        self.brought_forward = True


def test_open_window_brings_existing_window_forward_instead_of_recreating(monkeypatch):
    fake = FakeWindow()
    monkeypatch.setattr(native_window, "_window", fake)

    native_window.open_window()

    assert fake.brought_forward is True
