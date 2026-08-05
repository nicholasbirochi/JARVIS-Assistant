import subprocess

import pytest

from jarvis.voice import tts


def test_speak_calls_say_with_configured_voice(monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
    monkeypatch.setattr(subprocess, "run", lambda args, check: calls.append(args))

    tts.speak("olá")

    assert calls == [["say", "-v", "com.apple.voice.enhanced.pt-BR.Felipe", "olá"]]


def test_speak_falls_back_when_configured_voice_is_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(tts, "TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")

    def fake_run(args, check):
        calls.append(args)
        if args[2] == "com.apple.voice.enhanced.pt-BR.Felipe":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", fake_run)

    tts.speak("olá")

    assert calls == [
        ["say", "-v", "com.apple.voice.enhanced.pt-BR.Felipe", "olá"],
        ["say", "-v", tts.FALLBACK_VOICE, "olá"],
    ]


def test_speak_raises_when_even_the_fallback_voice_fails(monkeypatch):
    monkeypatch.setattr(tts, "TTS_VOICE", tts.FALLBACK_VOICE)

    def always_fails(args, check):
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(subprocess, "run", always_fails)

    with pytest.raises(subprocess.CalledProcessError):
        tts.speak("olá")
