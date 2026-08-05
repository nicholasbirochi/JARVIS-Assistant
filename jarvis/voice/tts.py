"""Text-to-speech via the macOS `say` command -- offline, free, no setup."""

from __future__ import annotations

import subprocess
import sys

from jarvis.config import TTS_VOICE

# Bundled by macOS itself (com.apple.voice.compact.*), never requires a
# separate download -- the last-resort fallback if TTS_VOICE isn't available
# (an Enhanced voice downloaded on this Mac doesn't exist after a fresh
# macOS install or a move to another machine; `say` errors out instead of
# silently substituting for an unknown *identifier*, unlike an unknown bare
# name, which it silently swaps for the default voice instead).
FALLBACK_VOICE = "com.apple.voice.compact.pt-BR.Luciana"


def speak(text: str) -> None:
    try:
        subprocess.run(["say", "-v", TTS_VOICE, text], check=True)
    except subprocess.CalledProcessError:
        if TTS_VOICE == FALLBACK_VOICE:
            raise  # already the fallback -- nothing left to degrade to
        print(f"[tts] voz {TTS_VOICE!r} indisponível, usando {FALLBACK_VOICE!r}", file=sys.stderr)
        subprocess.run(["say", "-v", FALLBACK_VOICE, text], check=True)
