"""Opens the HUD (jarvis/visualizer/server.py) in its own chrome-less
window instead of a regular browser tab -- launches Playwright's already-
downloaded Chromium build in `--app=` mode, which drops the tab strip,
address bar, and bookmarks bar, so it reads as a standalone app window.
No new dependency (that Chromium build is already required for
jarvis/sites/) and no PyObjC/WebKit window-management code to maintain.

Falls back to the default browser if that Chromium build isn't installed
(`playwright install chromium` never run) -- degrades, doesn't break."""

from __future__ import annotations

import subprocess
import webbrowser

from jarvis.visualizer import server

_process: subprocess.Popen | None = None


def _chromium_executable_path() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None

    try:
        p = sync_playwright().start()
    except Exception:
        return None
    try:
        path = p.chromium.executable_path
        return path if path else None
    except Exception:
        return None
    finally:
        p.stop()


def open_window() -> None:
    """Opens the HUD in its own window, or just leaves it alone if one
    from this menu-bar process is already open -- safe to click the menu
    item repeatedly without stacking up duplicate windows."""
    global _process

    if _process is not None and _process.poll() is None:
        return

    url = server.url()
    chromium = _chromium_executable_path()
    if chromium is None:
        webbrowser.open(url)
        return

    from jarvis.config import LOCAL_STATE_DIR

    profile_dir = LOCAL_STATE_DIR / "visualizer" / "chromium-profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _process = subprocess.Popen(
        [
            chromium,
            f"--app={url}",
            "--window-size=560,680",
            f"--user-data-dir={profile_dir}",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
