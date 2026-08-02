"""Text-to-speech via the macOS `say` command -- offline, free, no setup."""

from __future__ import annotations

import subprocess

from jarvis.config import TTS_VOICE


def speak(text: str) -> None:
    subprocess.run(["say", "-v", TTS_VOICE, text], check=True)
