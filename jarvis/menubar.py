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

main() refuses to start a second instance (a PID lock file under
LOCAL_STATE_DIR) -- found live that two real instances (the LaunchAgent's
+ a manually-opened JARVIS.app) ended up running at once, both fighting
over the microphone, which is exactly the kind of confusing, silent
failure this project has chased down more than once already.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

import rumps
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSWorkspace,
    NSWorkspaceDidWakeNotification,
)

from jarvis.assistant.conversation import run_voice_loop

_ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ICON_OFF = str(_ASSETS_DIR / "icon_off.png")
ICON_ON = str(_ASSETS_DIR / "icon_on.png")


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else -- still alive
    return True


def _acquire_singleton_lock() -> bool:
    """Returns True if this process should proceed (no other JARVIS
    instance currently holds the lock), False if one already does --
    caller must exit immediately in that case, not start a second
    wake-word listener/mic stream. A lock left behind by a hard-killed
    previous instance is harmless: its PID is checked for being alive,
    not just present, so a stale file never blocks a fresh start."""
    from jarvis.config import LOCAL_STATE_DIR

    lock_path = LOCAL_STATE_DIR / "jarvis.pid"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing_pid = int(lock_path.read_text().strip())
        except ValueError:
            existing_pid = None
        if existing_pid is not None and existing_pid != os.getpid() and _pid_is_alive(existing_pid):
            return False

    lock_path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def _notify_already_running() -> None:
    # No rumps.App/NSApplication exists yet at this point (we're refusing
    # to create one) -- osascript's own notification mechanism works
    # standalone, so a second double-click gives real feedback instead of
    # silently doing nothing (again).
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                'display notification "Já tem uma instância rodando." with title "JARVIS"',
            ],
            check=False,
            timeout=5,
        )
    except Exception:
        pass


class VoiceLoopController:
    """Owns the background thread running the voice loop. Kept separate
    from JarvisMenuBarApp so the on/off logic is unit-testable without
    touching rumps/AppKit at all -- same reasoning as conversation.py's
    _run_active_session extraction."""

    def __init__(self, target: Callable[..., None] = run_voice_loop) -> None:
        self._target = target
        self._stop_event: threading.Event | None = None
        self._wake_event: threading.Event | None = None
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread = threading.Thread(
            target=self._target,
            kwargs={"stop_event": self._stop_event, "wake_event": self._wake_event},
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        # No join() here -- the target exits on its own (within one wait()
        # cycle if idle, or once the current conversation naturally ends)
        # and blocking the menu-click handler on that would freeze the UI.
        if self._stop_event is not None:
            self._stop_event.set()

    def notify_system_wake(self) -> None:
        """Called from a real NSWorkspace wake notification (see
        JarvisMenuBarApp below). No-ops while off -- there's no listener
        to refresh, and it'll get a fresh one anyway next time start() is
        called."""
        if self._wake_event is not None:
            self._wake_event.set()


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
        # Real, confirmed failure mode, not speculative: a session ran for
        # hours, the machine went through an actual macOS Clamshell Sleep,
        # and wake-word detection silently stopped firing afterward -- no
        # exception anywhere, the mic stream just quietly stopped
        # delivering real frames. This is the genuine OS-level signal for
        # "the machine just woke up"; see WakeWordListener.wait()'s
        # docstring for what happens with it. Kept as an attribute (not a
        # bare local) so the observer token isn't garbage-collected.
        self._wake_observer = (
            NSWorkspace.sharedWorkspace()
            .notificationCenter()
            .addObserverForName_object_queue_usingBlock_(
                NSWorkspaceDidWakeNotification, None, None, lambda _note: self._controller.notify_system_wake()
            )
        )

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
    if not _acquire_singleton_lock():
        print("[jarvis] outra instância já está rodando -- encerrando esta.", file=sys.stderr)
        _notify_already_running()
        return
    JarvisMenuBarApp().run()


if __name__ == "__main__":
    main()
