"""Text-to-speech via the macOS `say` command -- offline, free, no setup."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from jarvis.config import TTS_VOICE

# Bundled by macOS itself (com.apple.voice.compact.*), never requires a
# separate download -- the last-resort fallback if TTS_VOICE isn't available
# (an Enhanced voice downloaded on this Mac doesn't exist after a fresh
# macOS install or a move to another machine; `say` errors out instead of
# silently substituting for an unknown *identifier*, unlike an unknown bare
# name, which it silently swaps for the default voice instead).
FALLBACK_VOICE = "com.apple.voice.compact.pt-BR.Luciana"

# How often to check stop_event while `say` is running -- fine-grained
# enough that clicking "Desligar JARVIS" mid-sentence feels instant rather
# than waiting out however long the current sentence takes.
_POLL_SECONDS = 0.05


def _speak_uninterruptible(voice: str, text: str) -> bool:
    return subprocess.run(["say", "-v", voice, text]).returncode == 0


def _speak_interruptible(voice: str, text: str, stop_event: threading.Event) -> bool:
    """Runs `say`, killing it early the moment stop_event fires. Returns
    True if it finished speaking normally, False on a real failure (e.g.
    voice not found) -- being interrupted on purpose counts as True, since
    it's not a failure that should trigger a fallback-voice retry."""
    process = subprocess.Popen(["say", "-v", voice, text])
    while process.poll() is None:
        if stop_event.is_set():
            process.terminate()
            process.wait()
            return True
        time.sleep(_POLL_SECONDS)
    return process.returncode == 0


def speak(text: str, stop_event: threading.Event | None = None) -> None:
    """Speaks `text` aloud. If `stop_event` is given (the menu bar's
    off-toggle sets it) and fires while this is talking, the `say` process
    is killed immediately -- "Desligar JARVIS" cuts him off right away
    instead of finishing the current sentence first."""
    if stop_event is not None:
        ok = _speak_interruptible(TTS_VOICE, text, stop_event)
    else:
        ok = _speak_uninterruptible(TTS_VOICE, text)
    if ok:
        return

    if TTS_VOICE == FALLBACK_VOICE:
        raise RuntimeError(f"say -v {TTS_VOICE!r} falhou")

    print(f"[tts] voz {TTS_VOICE!r} indisponível, usando {FALLBACK_VOICE!r}", file=sys.stderr)
    if stop_event is not None:
        ok = _speak_interruptible(FALLBACK_VOICE, text, stop_event)
    else:
        ok = _speak_uninterruptible(FALLBACK_VOICE, text)
    if not ok:
        raise RuntimeError(f"say -v {FALLBACK_VOICE!r} falhou")
