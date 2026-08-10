"""Text-to-speech. Default is the macOS `say` command -- offline, free, no
setup. When TTS_ENGINE="xtts" and a reference clip + a ready worker
process are both available (see jarvis/voice/xtts_client.py and
xtts_engine.py), speak() clones a voice from that clip instead; otherwise
it transparently falls back to `say` below, so flipping TTS_ENGINE never
breaks anything even before the reference clip exists or while the worker
is still starting up/loading its model.

The xtts path streams: PCM chunks are piped into `ffplay` as they arrive
from the worker (jarvis/voice/xtts_client.py's synthesize_stream()) rather
than waiting for a whole utterance to finish generating first and only
then playing a file. Measured live: XTTS synthesis for a short reply takes
around 5s on this hardware -- streaming means audio starts within about a
second of that instead of JARVIS sitting silent for the whole thing."""

from __future__ import annotations

import itertools
import subprocess
import sys
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


def _ffplay_command(sample_rate: int) -> list[str]:
    # Raw PCM straight in via stdin -- no temp file, no waiting for a
    # whole WAV to exist first. ffmpeg is already a required system
    # dependency here (xtts_engine.py's docstring), so ffplay comes free.
    #
    # No "-ac 1": a real bug, confirmed live -- this ffmpeg build (8.1.2)
    # doesn't recognize "-ac" as a valid option for the raw s16le demuxer
    # at all ("Failed to set value '1' for option 'ac': Option not
    # found"), so ffplay exited immediately with no audio and no fallback
    # (the failure happens after _speak_via_xtts already commits to the
    # xtts path). Confirmed via `ffmpeg -h demuxer=s16le` that "mono" is
    # already this demuxer's own default channel layout -- which is
    # exactly what xtts_engine.synthesize_stream() produces, so the flag
    # was never actually necessary, not just wrong.
    return ["ffplay", "-f", "s16le", "-ar", str(sample_rate), "-nodisp", "-autoexit", "-loglevel", "quiet", "-"]


def _speak_via_xtts(text: str, stop_event: threading.Event | None) -> bool:
    """Returns True if xtts handled it (including "generation/playback was
    interrupted on purpose" -- that's not a failure, and must NOT fall
    through to the say-based voice repeating the same text). Returns False
    to tell the caller to use the say-based path instead -- either xtts
    isn't ready yet (no reference clip, or the isolated worker process is
    still loading), or generation failed before any audio was produced.
    Talks to xtts_client, not xtts_engine directly -- synthesis runs in
    its own OS process, see xtts_engine.py's module docstring for why.

    Streams: pipes PCM chunks into ffplay as xtts_client.synthesize_stream()
    yields them, rather than waiting for the whole utterance to finish and
    only then playing a file -- the real, measured ~5s of silence per
    reply that was the whole point of this rewrite. Once the first chunk
    has actually started playing, a later failure just stops audio instead
    of falling back to say (that would repeat the reply out loud in a
    different voice, worse than a slightly short cutoff)."""
    from jarvis.voice import xtts_client
    from jarvis.voice.xtts_engine import STREAM_SAMPLE_RATE

    if not xtts_client.has_reference_audio() or not xtts_client.is_ready():
        return False

    try:
        chunk_iter = xtts_client.synthesize_stream(text)
        first_chunk = next(chunk_iter, None)
    except Exception as exc:
        print(f"[tts] XTTS falhou ({exc}), usando voz de fallback", file=sys.stderr)
        return False

    if first_chunk is None:
        return True  # empty synthesis (e.g. empty text) -- nothing to play, not a failure

    if stop_event is not None and stop_event.is_set():
        # Told to shut up before any audio was even queued up to play.
        return True

    try:
        process = subprocess.Popen(_ffplay_command(STREAM_SAMPLE_RATE), stdin=subprocess.PIPE)
    except OSError as exc:
        # Real gap this closes: ffplay itself failing to even start (not
        # found, no permission, whatever) used to propagate uncaught out
        # of speak() entirely -- silent total failure, no sound at all and
        # no fallback, instead of the graceful say-based degrade every
        # other failure in this function gets.
        print(f"[tts] não consegui iniciar o ffplay ({exc}), usando voz de fallback", file=sys.stderr)
        return False

    try:
        for chunk in itertools.chain((first_chunk,), chunk_iter):
            if stop_event is not None and stop_event.is_set():
                break
            try:
                process.stdin.write(chunk)
            except (BrokenPipeError, OSError):
                break  # ffplay exited on its own (e.g. real failure) -- nothing left to feed it
    finally:
        try:
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        while process.poll() is None:
            if stop_event is not None and stop_event.is_set():
                process.terminate()
                break
            time.sleep(_POLL_SECONDS)
        process.wait()
        if process.returncode not in (0, None) and not (stop_event is not None and stop_event.is_set()):
            # Not raised/fallen back to say at this point -- some audio
            # may already have played -- but worth a clear signal in the
            # log instead of silently pretending this went fine.
            print(f"[tts] ffplay saiu com código {process.returncode} (áudio pode ter ficado incompleto)", file=sys.stderr)
    return True


def speak(text: str, stop_event: threading.Event | None = None) -> None:
    """Speaks `text` aloud. If `stop_event` is given (the menu bar's
    off-toggle sets it) and fires while this is talking, playback is killed
    immediately -- "Desligar JARVIS" cuts him off right away instead of
    finishing the current sentence first.

    The visualizer transcript shows `text` with markdown stripped (a
    stray "`code`" or "**bold**" the model slipped in reads as literal
    backticks/asterisks otherwise -- this HUD has no markdown renderer,
    it's plain textContent, see jarvis/visualizer/page.html), but
    acronyms stay as written ("IA"). What's actually synthesized goes
    further: acronyms get spelled out too ("IA" -> "I.A.") so say/XTTS
    pronounce them letter by letter instead of as a word -- display and
    speech are deliberately different strings from that point on."""
    from jarvis.visualizer import state as visualizer_state
    from jarvis.voice.speech_text import spell_out_acronyms, strip_markdown

    display_text = strip_markdown(text)
    visualizer_state.publish("speaking", text=display_text)
    spoken_text = spell_out_acronyms(display_text)

    if TTS_ENGINE == "xtts" and _speak_via_xtts(spoken_text, stop_event):
        return

    if stop_event is not None:
        ok = _speak_interruptible(TTS_VOICE, spoken_text, stop_event)
    else:
        ok = _speak_uninterruptible(TTS_VOICE, spoken_text)
    if ok:
        return

    if TTS_VOICE == FALLBACK_VOICE:
        raise RuntimeError(f"say -v {TTS_VOICE!r} falhou")

    print(f"[tts] voz {TTS_VOICE!r} indisponível, usando {FALLBACK_VOICE!r}", file=sys.stderr)
    if stop_event is not None:
        ok = _speak_interruptible(FALLBACK_VOICE, spoken_text, stop_event)
    else:
        ok = _speak_uninterruptible(FALLBACK_VOICE, spoken_text)
    if not ok:
        raise RuntimeError(f"say -v {FALLBACK_VOICE!r} falhou")
