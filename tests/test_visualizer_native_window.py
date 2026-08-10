"""Only the pure-Python idempotency logic is covered here -- actually
creating an NSWindow/WKWebView is real Cocoa UI (verified manually, live,
via a screenshot: see the commit this file was added in) and isn't
unit-tested, matching jarvis/menubar.py's own JarvisMenuBarApp precedent
of leaving real AppKit object creation to manual/live verification."""

from jarvis.visualizer import native_window


class FakeWindow:
    def __init__(self, visible=False):
        self.brought_forward = False
        self.closed = False
        self._visible = visible

    def makeKeyAndOrderFront_(self, _sender):
        self.brought_forward = True
        self._visible = True

    def close(self):
        self.closed = True
        self._visible = False

    def isVisible(self):
        return self._visible


def test_open_window_brings_existing_window_forward_instead_of_recreating(monkeypatch):
    fake = FakeWindow()
    monkeypatch.setattr(native_window, "_window", fake)

    native_window.open_window()

    assert fake.brought_forward is True


def test_close_window_closes_the_existing_window(monkeypatch):
    fake = FakeWindow(visible=True)
    monkeypatch.setattr(native_window, "_window", fake)

    native_window.close_window()

    assert fake.closed is True


def test_close_window_before_any_open_is_a_safe_no_op(monkeypatch):
    monkeypatch.setattr(native_window, "_window", None)

    native_window.close_window()  # must not raise


def test_is_open_false_before_any_window_exists(monkeypatch):
    monkeypatch.setattr(native_window, "_window", None)

    assert native_window.is_open() is False


def test_is_open_true_once_visible(monkeypatch):
    monkeypatch.setattr(native_window, "_window", FakeWindow(visible=True))

    assert native_window.is_open() is True


def test_is_open_false_after_the_window_reports_not_visible(monkeypatch):
    # Covers the user closing it via the window's own native close button,
    # not just via close_window() -- _window still exists (never
    # deallocated, see setReleasedWhenClosed_(False)), just not visible.
    monkeypatch.setattr(native_window, "_window", FakeWindow(visible=False))

    assert native_window.is_open() is False
