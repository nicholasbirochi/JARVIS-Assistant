"""macOS menu bar app: a single click starts/stops JARVIS's voice-listening
loop, running in a background thread so the menu itself stays responsive.

Launched manually (`python -m jarvis menubar`) -- never auto-starts at
login, and starts OFF -- listening only begins once you click the toggle.

Icons are template PNGs rendered from SF Symbols (see
scripts/generate_menubar_icons.py) -- macOS tints them to match every other
native menu-bar icon (monochrome, adapts to light/dark) instead of showing
a colored emoji.

"Visualizar Interação" opens jarvis/visualizer/'s live HUD in a real
native window (jarvis/visualizer/native_window.py, WKWebView -- no
browser process involved at all) -- works independently of the on/off
toggle above, since it's just a window onto whatever state is currently
published (including "off" itself, published here -- see toggle() and
_sync_with_reality() -- since jarvis/assistant/conversation.py only ever
knows "idle/listening/speaking", never that it was stopped).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

import rumps
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory

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
        # rumps never sets an activation policy, so by default this process
        # (literally "Python", since there's no .app bundle) shows a Dock
        # icon and grabs Cmd-Tab like a regular foreground app. Accessory
        # policy makes it a pure menu-bar presence -- no Dock, no Cmd-Tab.
        NSApplication.sharedApplication().setActivationPolicy_(
            NSApplicationActivationPolicyAccessory
        )
        self._visualizer_item = rumps.MenuItem("Visualizar Interação", callback=self.open_visualizer)
        self._toggle_item = rumps.MenuItem("Ligar", callback=self.toggle)
        self.menu = [self._visualizer_item, self._toggle_item]
        self._controller = VoiceLoopController()  # starts OFF -- see module docstring
        # run_voice_loop now survives most failures on its own (see its
        # docstring), but if it ever does die unrecovered, this is what
        # stops the icon/title from claiming "on" forever afterward --
        # otherwise there'd be no visible sign JARVIS stopped responding.
        rumps.Timer(self._sync_with_reality, 5).start()

    def _sync_with_reality(self, _timer: rumps.Timer) -> None:
        if self._toggle_item.title == "Desligar" and not self._controller.is_running:
            self.icon = ICON_OFF
            self._toggle_item.title = "Ligar"
            self._publish_off()

    def toggle(self, _sender: rumps.MenuItem) -> None:
        if self._controller.is_running:
            self._controller.stop()
            self.icon = ICON_OFF
            self._toggle_item.title = "Ligar"
            self._publish_off()
        else:
            self._controller.start()
            self.icon = ICON_ON
            self._toggle_item.title = "Desligar"
            # No explicit "listening"/"idle" publish here -- run_voice_loop
            # itself publishes "idle" within its first loop iteration,
            # moments after the thread starts.

    @staticmethod
    def _publish_off() -> None:
        from jarvis.visualizer import state

        state.publish("off")

    def open_visualizer(self, _sender: rumps.MenuItem) -> None:
        # Works whether or not JARVIS is currently listening -- the HUD
        # just shows "Desligado" until a real state is published. Safe to
        # click repeatedly -- open_window() brings the existing window
        # forward instead of stacking up duplicates.
        from jarvis.visualizer import native_window

        native_window.open_window()


def main() -> None:
    JarvisMenuBarApp().run()


if __name__ == "__main__":
    main()
