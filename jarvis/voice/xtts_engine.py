"""XTTS-v2 voice cloning backend (github.com/idiap/coqui-ai-TTS, the
maintained fork -- the original coqui-ai/TTS is abandoned and doesn't run
on Python 3.12). Clones a voice from a short reference clip instead of
using one of macOS's built-in `say` voices; see tts.py for how this fits
into the overall speak() fallback chain.

Real, measured findings on this machine (M5, 24GB RAM, MPS available) that
shape the design here, not assumptions:
- Confirmed live with a real reference clip: loading takes ~13s, and
  generation runs at roughly real-time to faster (7.8s for a 7s reply,
  21.3s for a 29.7s reply -- 0.72x). Needs FFmpeg installed on the system
  (`brew install ffmpeg`) -- torchaudio's decoder loads its shared
  libraries at runtime; without it, synthesis fails with a clear
  "Could not load libtorchcodec" error.
- One earlier, isolated run -- before the real reference clip existed, using
  one of the model's own built-in preset voices -- took 15-17 minutes to
  load, for a reason never identified and never reproduced since. As a
  precaution the model still loads exactly ONCE per process on a background
  thread rather than being reloaded per-conversation (like stt.py does):
  preload_in_background() is meant to be called once, as early as possible
  (JARVIS startup, not first speak()), so even a repeat of that slow case
  would overlap with the user just having JARVIS on rather than blocking
  their first activation.
- That same earlier (pre-real-clip) comparison measured CPU as faster than
  MPS for this specific model (3.4s vs 11.4s to generate the same short
  sentence) -- MPS being "available" doesn't mean every op in this model
  has an efficient MPS kernel; per-op CPU fallback overhead can lose to
  just using CPU outright. device is hardcoded to "cpu" below for that
  reason, not auto-detected.

CURRENTLY NOT WIRED INTO THE LIVE VOICE LOOP: found live that
preload_in_background(), when called from conversation.py's
run_voice_loop, made torchcodec dlopen the Homebrew-installed FFmpeg into
the same process that already has faster-whisper's own bundled FFmpeg
(via PyAV) loaded -- macOS logged a real ObjC class collision
(AVFFrameReceiver/AVFAudioReceiver defined in both libavdevice copies),
and wake-word/clap detection stopped firing entirely, silently, right
after. See conversation.py's run_voice_loop docstring. This module is
otherwise complete and tested; it just needs XTTS synthesis to run in a
genuinely separate process before it's safe to preload alongside the
microphone listener again.
"""

from __future__ import annotations

import os
import sys
import threading

_model = None
_model_lock = threading.Lock()
_load_started = False


def has_reference_audio() -> bool:
    from jarvis.config import TTS_XTTS_SPEAKER_WAV_PATH  # live lookup -- monkeypatchable in tests

    return TTS_XTTS_SPEAKER_WAV_PATH.exists()


def is_ready() -> bool:
    with _model_lock:
        return _model is not None


def preload_in_background() -> None:
    """Starts loading the model on a background thread, at most once per
    process. No-ops if there's no reference clip yet -- no point paying the
    15+ minute cost (and the model's real memory footprint) for a voice
    that can't clone anything. Safe to call repeatedly (e.g. once per
    wake-word session) -- only the first call actually starts a thread."""
    global _load_started

    if not has_reference_audio():
        return

    with _model_lock:
        if _load_started:
            return
        _load_started = True

    threading.Thread(target=_load, daemon=True, name="xtts-preload").start()


def _build_model():
    """Split out from _load() purely so tests can make this step fail
    without needing to fight a real (or really-absent) TTS import."""
    os.environ.setdefault("COQUI_TOS_AGREED", "1")  # personal, local, non-commercial use
    from TTS.api import TTS

    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")


def _load() -> None:
    global _model

    try:
        model = _build_model()
    except Exception as exc:
        # Runs on a daemon thread -- an uncaught exception here would just
        # print a traceback nobody's watching and silently leave is_ready()
        # False forever. tts.py already falls back to the say-based voice
        # whenever that's the case, so this is a degrade, not a crash --
        # but it should say why, not fail silently.
        print(
            f"[xtts] falha ao carregar o modelo ({exc}) -- dependências de "
            "voice-cloning instaladas? `pip install -e '.[voice-cloning]'`. "
            "Usando a voz padrão (say) por enquanto.",
            file=sys.stderr,
        )
        return

    with _model_lock:
        _model = model


def synthesize_to_file(text: str, out_path: str) -> None:
    """Raises RuntimeError if the model isn't loaded yet or there's no
    reference clip -- callers (tts.py) must check is_ready() /
    has_reference_audio() first and fall back to the fast voice instead of
    calling this speculatively."""
    from jarvis.config import TTS_XTTS_LANGUAGE, TTS_XTTS_SPEAKER_WAV_PATH

    with _model_lock:
        model = _model
    if model is None:
        raise RuntimeError("modelo XTTS ainda não carregado")

    model.tts_to_file(
        text=text,
        speaker_wav=str(TTS_XTTS_SPEAKER_WAV_PATH),
        language=TTS_XTTS_LANGUAGE,
        file_path=out_path,
    )
