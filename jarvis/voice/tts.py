"""Text-to-speech. Default is the macOS `say` command -- offline, free, no
setup. When TTS_ENGINE="xtts" and a reference clip + loaded model are both
available (see jarvis/voice/xtts_engine.py), speak() clones a voice from
that clip instead; otherwise it transparently falls back to `say` below, so
flipping TTS_ENGINE never breaks anything even before the reference clip
exists or while the (very slow) model is still loading."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time

from jarvis.config import TTS_ENGINE, TTS_VOICE

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


def _play_file_uninterruptible(path: str) -> bool:
    return subprocess.run(["afplay", path]).returncode == 0


def _play_file_interruptible(path: str, stop_event: threading.Event) -> bool:
    process = subprocess.Popen(["afplay", path])
    while process.poll() is None:
        if stop_event.is_set():
            process.terminate()
            process.wait()
            return True
        time.sleep(_POLL_SECONDS)
    return process.returncode == 0


def _speak_via_xtts(text: str, stop_event: threading.Event | None) -> bool:
    """Returns True if xtts handled it (including "generation/playback was
    interrupted on purpose" -- that's not a failure, and must NOT fall
    through to the say-based voice repeating the same text). Returns False
    to tell the caller to use the say-based path instead -- either xtts
    isn't ready yet (no reference clip, or the model is still in its
    15+ minute load), or generation itself failed."""
    from jarvis.voice import xtts_engine

    if not xtts_engine.has_reference_audio() or not xtts_engine.is_ready():
        return False

    fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        xtts_engine.synthesize_to_file(text, out_path)
    except Exception as exc:
        print(f"[tts] XTTS falhou ({exc}), usando voz de fallback", file=sys.stderr)
        os.unlink(out_path)
        return False

    try:
        if stop_event is not None and stop_event.is_set():
            # Told to shut up while audio was still generating -- don't
            # play stale speech after the fact.
            return True
        if stop_event is not None:
            return _play_file_interruptible(out_path, stop_event)
        return _play_file_uninterruptible(out_path)
    finally:
        os.unlink(out_path)


def speak(text: str, stop_event: threading.Event | None = None) -> None:
    """Speaks `text` aloud. If `stop_event` is given (the menu bar's
    off-toggle sets it) and fires while this is talking, playback is killed
    immediately -- "Desligar JARVIS" cuts him off right away instead of
    finishing the current sentence first."""
    if TTS_ENGINE == "xtts" and _speak_via_xtts(text, stop_event):
        return

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
