"""macOS menu bar app: a single click starts/stops JARVIS's voice-listening
loop, running in a background thread so the menu itself stays responsive.

Launched manually (`python -m jarvis menubar`) -- never auto-starts at
login. Starts already listening (matches what running `python -m jarvis`
directly already does) so switching to the menu-bar app isn't a step
backward; the button is there for whenever you want to turn it off.
"""

from __future__ import annotations

import threading
from typing import Callable

import rumps

from jarvis.assistant.conversation import run_voice_loop

ICON_OFF = "🤖"
ICON_ON = "🤖🎙️"


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
        super().__init__(ICON_OFF, quit_button="Sair")
        self._toggle_item = rumps.MenuItem("Desligar JARVIS", callback=self.toggle)
        self.menu = [self._toggle_item]
        self._controller = VoiceLoopController()
        self._controller.start()  # listening by default -- see module docstring
        self.title = ICON_ON

    def toggle(self, _sender: rumps.MenuItem) -> None:
        if self._controller.is_running:
            self._controller.stop()
            self.title = ICON_OFF
            self._toggle_item.title = "Ligar JARVIS"
        else:
            self._controller.start()
            self.title = ICON_ON
            self._toggle_item.title = "Desligar JARVIS"


def main() -> None:
    JarvisMenuBarApp().run()


if __name__ == "__main__":
    main()
