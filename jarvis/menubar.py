"""macOS menu bar app: a single click starts/stops JARVIS's voice-listening
loop, running in a background thread so the menu itself stays responsive.

Launched manually (`python -m jarvis menubar`) -- never auto-starts at
login, and starts OFF -- listening only begins once you click the toggle.

Icons are template PNGs rendered from SF Symbols (see
scripts/generate_menubar_icons.py) -- macOS tints them to match every other
native menu-bar icon (monochrome, adapts to light/dark) instead of showing
a colored emoji.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import rumps

from jarvis.assistant.conversation import run_voice_loop

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_OFF = str(_ASSETS_DIR / "icon_off.png")
ICON_ON = str(_ASSETS_DIR / "icon_on.png")


class VoiceLoopController:
    """Owns the background thread running the voice loop. Kept separate
    from JarvisMenuBarApp so the on/off logic is unit-testable without
    touching rumps/AppKit at all -- same reasoning as conversation.py's
    _run_active_session extraction."""

    def __init__(self, target: Callable[..., None] = run_voice_loop) -> None:
        self._target = target
        self._stop_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._target, kwargs={"stop_event": self._stop_event}, daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        # No join() here -- the target exits on its own (within one wait()
        # cycle if idle, or once the current conversation naturally ends)
        # and blocking the menu-click handler on that would freeze the UI.
        if self._stop_event is not None:
            self._stop_event.set()


class JarvisMenuBarApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("JARVIS", icon=ICON_OFF, template=True, quit_button="Sair")
        self._toggle_item = rumps.MenuItem("Ligar JARVIS", callback=self.toggle)
        self.menu = [self._toggle_item]
        self._controller = VoiceLoopController()  # starts OFF -- see module docstring

    def toggle(self, _sender: rumps.MenuItem) -> None:
        if self._controller.is_running:
            self._controller.stop()
            self.icon = ICON_OFF
            self._toggle_item.title = "Ligar JARVIS"
        else:
            self._controller.start()
            self.icon = ICON_ON
            self._toggle_item.title = "Desligar JARVIS"


def main() -> None:
    JarvisMenuBarApp().run()


if __name__ == "__main__":
    main()
