"""Real native window for the HUD (jarvis/visualizer/server.py) via
WebKit's WKWebView directly -- Apple's own browser engine (same one
Safari uses), no Chrome/browser process involved at all. Chosen over the
Chromium `--app=` approach (jarvis/visualizer/launcher.py, now unused)
because that repurposed a Google testing build for interactive end-user
UI, and it showed its own "update Chrome" nag on top of the page --
undermining the whole point of looking like a real app.

Must be created on the main thread -- Cocoa (AppKit/WebKit) requires all
UI work to happen there. jarvis/menubar.py's click handlers already run
on the main thread (that's how rumps itself works), so open_window()
does no threading of its own."""

from __future__ import annotations

from jarvis.visualizer import server

_window = None
_webview = None


def open_window() -> None:
    """Opens the HUD in its own window, or brings the existing one
    forward if already open -- safe to call repeatedly."""
    global _window, _webview

    if _window is not None:
        _window.makeKeyAndOrderFront_(None)
        return

    from AppKit import (
        NSBackingStoreBuffered,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSMakeRect, NSURL, NSURLRequest
    from WebKit import WKWebView

    rect = NSMakeRect(200, 200, 560, 680)
    style = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskMiniaturizable
        | NSWindowStyleMaskResizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, style, NSBackingStoreBuffered, False
    )
    window.setTitle_("J • A • R • V • I • S")
    # Keeps the NSWindow object alive (not deallocated) when the user
    # clicks the close button, so a later open_window() call can bring the
    # same window back with makeKeyAndOrderFront_ instead of needing to
    # rebuild the whole WKWebView from scratch each time.
    window.setReleasedWhenClosed_(False)

    webview = WKWebView.alloc().initWithFrame_(rect)
    webview.loadRequest_(NSURLRequest.requestWithURL_(NSURL.URLWithString_(server.url())))
    window.setContentView_(webview)
    window.center()
    window.makeKeyAndOrderFront_(None)

    _window = window
    _webview = webview


def close_window() -> None:
    """Hides the HUD window -- safe to call even if it was never opened,
    or was already closed (including by the user clicking the window's
    own native close button, not this). setReleasedWhenClosed_(False) in
    open_window() means this never deallocates the window/webview, so a
    later open_window() call can bring the exact same one back instead of
    rebuilding it from scratch."""
    if _window is not None:
        _window.close()


def is_open() -> bool:
    """Whether the HUD window is currently visible -- False both before
    the first open_window() call and after the user closes it via the
    window's own close button, not just via close_window() above. Used by
    jarvis/menubar.py to keep its menu item label truthful regardless of
    which way the window actually got closed."""
    return _window is not None and _window.isVisible()
