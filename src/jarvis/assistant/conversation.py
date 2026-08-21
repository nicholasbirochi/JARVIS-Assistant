"""The conversation state machine: IDLE (wake-word listening) -> ACTIVE
(listen/transcribe/respond loop) -> stop phrase -> back to IDLE.

Deliberately silent right after the wake word/clap fires -- no spoken
greeting, no proactive briefing anymore. Real complaint this fixes: JARVIS
used to speak a greeting immediately on activation, before the user had
said anything at all -- both premature ("não comece falando logo de
cara") and the actual cause of a real, confirmed voice bug: that greeting
raced xtts_worker's ~15-20s model-load time, so it very often used the
say-based fallback voice while every later reply (once the worker had
caught up) used the real cloned one, an inconsistency that read as the
voice "bugando". Activation now just transitions to "listening" (see
_run_active_session) and waits for the user's own first utterance --
GREETING/CLAP_GREETING (jarvis/config.py) are only spoken in text mode
(run_text_loop below), never through TTS, so they can't race anything.

Each state transition (idle/listening/thinking; "speaking" fires from
tts.speak() itself, see jarvis/voice/tts.py) is published to
jarvis/visualizer/state.py -- purely a live visual aid (the menu bar's
"Visualizar Interação" button), never read back by anything here.
"Thinking" covers the real gap between the user finishing an utterance
and JARVIS starting to speak the reply (STT already ran by then; what's
left is the LLM call) -- without it, the HUD kept showing "Ouvindo..."
long after the user had stopped talking, indistinguishable from actually
still listening.

Every reply/greeting/briefing is spoken through `_speak_with_barge_in`,
which watches the mic concurrently while talking: saying the wake word
mid-sentence interrupts JARVIS immediately, same as the menu bar's
off-toggle already did for `stop_event`. Deliberately NOT a clap, even
though a clap can activate JARVIS from idle -- clap detection is plain
peak-amplitude noise detection, not real voice recognition, so it's not
a safe signal to interrupt an in-progress reply on (see
_speak_with_barge_in's own docstring for the real complaint this fixes).
"""

from __future__ import annotations

import threading

from jarvis.assistant.llm_client import send_turn
from jarvis.config import GREETING, STOP_PHRASES
from jarvis.voice import tts
from jarvis.voice import audio, stt

GOODBYE = "Até logo, Senhor Nicholas."
MAX_CONSECUTIVE_EMPTY_TRANSCRIPTIONS = 3


def _is_stop_phrase(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".!")
    return normalized in STOP_PHRASES


def _speak_with_barge_in(speak, text: str, listener, stop_event: threading.Event | None = None):
    """Speaks `text`, but concurrently watches the mic for a deliberate
    interruption -- the wake word ONLY, not a clap. The moment it fires,
    speech is cut short right away instead of finishing the current
    sentence -- the caller doesn't need to do anything special afterward:
    the loops in this module already go straight back to listening next,
    whether speech ran to completion or was barged in on.

    Deliberately excludes the clap trigger here (check_trigger(...,
    include_clap=False)) -- real complaint this fixes: clap detection is
    plain peak-amplitude noise detection (see clap_detector.py), not
    actual voice recognition, so any sufficiently loud, sharp sound (a
    dropped object, a door) could cut JARVIS off mid-sentence with nothing
    said at all. Clap-to-activate from idle is unaffected -- see wait()
    and check_trigger()'s own docstring.

    Known limitation, not attempted here: no acoustic echo cancellation,
    so JARVIS's own voice playing through the speakers could in principle
    trigger a false interrupt if it happens to say something close enough
    to the wake phrase. The wake-word engine is tuned against real speech,
    not JARVIS's own TTS output, so this is expected to be rare in
    practice -- worth revisiting with a real headset/AEC setup if it
    turns out not to be.

    Returns "wake_word" if that's what interrupted speech, or None if
    speech completed normally or was stopped via `stop_event` (e.g.
    "Desligar JARVIS")."""
    watch_event = threading.Event()
    detected: list[str | None] = [None]

    def _watch() -> None:
        while not watch_event.is_set():
            if stop_event is not None and stop_event.is_set():
                watch_event.set()
                return
            frame = listener.read_frame()
            trigger = listener.check_trigger(frame, include_clap=False)
            if trigger is not None:
                detected[0] = trigger
                watch_event.set()
                return

    watcher = threading.Thread(target=_watch, daemon=True)
    watcher.start()
    try:
        speak(text, stop_event=watch_event)
    finally:
        watch_event.set()  # in case speak() returned on its own (finished, or a real failure) -- stop the watcher either way
        # No timeout here, deliberately -- a real bug hit shipping this:
        # WakeWordListener's underlying PvRecorder stream isn't safe for
        # concurrent reads. With a bounded join, if the watcher thread was
        # still blocked inside read_frame() when the join gave up, the
        # caller would move on to its own record_utterance()/wait() call
        # on the very same recorder while the watcher was STILL reading
        # from it -- two threads pulling frames off one stream at once,
        # which corrupted wake-word detection for the rest of the process
        # (JARVIS would activate once, then never hear the wake word
        # again). An unbounded join guarantees the watcher has genuinely
        # stopped calling read_frame() before this function returns --
        # worst case adds one frame's duration (tens of ms) of wait, never
        # more, since the watcher checks watch_event right after every read.
        watcher.join()
    return detected[0]


def run_text_loop() -> None:
    from jarvis.assistant.briefing import build_briefing

    print(GREETING)
    briefing = build_briefing()
    if briefing:
        print(f"JARVIS: {briefing}")
    messages: list[dict] = []
    while True:
        try:
            text = input("Você: ").strip()
        except EOFError:
            break
        if not text:
            continue
        if _is_stop_phrase(text):
            print(f"JARVIS: {GOODBYE}")
            break
        messages.append({"role": "user", "content": text})
        reply = send_turn(messages)
        print(f"JARVIS: {reply}")


def _run_active_session(
    listener, record_utterance, transcribe, speak, stop_event: threading.Event | None = None
) -> None:
    """One wake-word session's ACTIVE loop, with its dependencies passed in
    so it's testable without real audio/model/TTS. Always unloads the STT
    model on the way out -- whether the session ended via stop phrase or via
    the walk-away fallback below -- since this is the natural, instantaneous
    "session over" boundary: the model stays resident for the whole
    multi-turn conversation (no per-turn reload cost) and frees the moment
    it ends, no idle-timeout thread needed.

    `stop_event` is forwarded to every `speak()` call so "Desligar JARVIS"
    (the menu bar's off-toggle) interrupts speech that's already in
    progress instead of waiting for the current sentence to finish. Every
    reply is also spoken via `_speak_with_barge_in` so saying the wake
    word or clapping again while JARVIS is still talking interrupts it the
    same way -- see that function's docstring."""
    from jarvis.visualizer import state as visualizer_state
    from jarvis.voice import stt

    messages: list[dict] = []
    consecutive_empty = 0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                # "Desligar JARVIS" mid-conversation -- a real gap: this
                # loop only ever ended via a stop phrase or the user
                # walking away, so the menu bar icon/HUD would flip to
                # "off" the instant it was clicked while the session (and
                # the mic) kept actually running underneath until one of
                # those fired. Checked once per turn, not mid-recording --
                # record_utterance() itself still isn't interruptible, so
                # this can't cut off a recording already in progress, but
                # it does mean JARVIS stops for real within one turn
                # instead of needing an explicit goodbye.
                return
            visualizer_state.publish("listening")
            pcm = record_utterance(listener)
            text = transcribe(pcm)

            if not text:
                consecutive_empty += 1
                # The user may have walked away without saying a stop phrase --
                # without this, the loop would otherwise spin forever on empty
                # transcriptions and stt.unload() below would never run.
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY_TRANSCRIPTIONS:
                    speak(GOODBYE, stop_event=stop_event)
                    return
                continue
            consecutive_empty = 0

            if _is_stop_phrase(text):
                speak(GOODBYE, stop_event=stop_event)
                return

            visualizer_state.publish("thinking")
            messages.append({"role": "user", "content": text})
            reply = send_turn(messages)
            if reply:
                _speak_with_barge_in(speak, reply, listener, stop_event=stop_event)
    finally:
        stt.unload()


def run_voice_loop(
    stop_event: threading.Event | None = None,
    wake_event: threading.Event | None = None,
) -> None:
    """Runs until an unhandled exception the microphone can't be recovered
    from, or (when `stop_event` is given, as the menu-bar app does) until
    it's set -- checked between wake-word sessions, so "off" takes effect
    immediately while idle, or as soon as the current conversation
    naturally ends if one is in progress. Speech already in progress is cut
    short right away too -- see `_run_active_session` and `tts.speak`.

    A single bad frame read (a real, observed failure: `pvrecorder` raising
    `OSError: Failed to read from device` after another process briefly
    grabbed the mic) used to kill this whole function silently -- the
    thread just died, the menu bar kept showing "on" forever after, and
    JARVIS simply stopped responding with no visible error short of
    digging through the log file. Any exception from one wake-word session
    now closes and rebuilds the listener and keeps going instead; only a
    genuinely broken microphone (the rebuild itself failing) actually ends
    the loop.

    `wake_event`, if given (the menu bar sets it from a real NSWorkspace
    wake notification), is forwarded to `listener.wait()` -- see its
    docstring. This is the *other* real mic-corruption case found live,
    distinct from the one above: no exception at all, the stream just
    quietly stops delivering real frames after the machine wakes from
    sleep, so there's nothing for the except block below to even catch."""
    import sys
    import time

    from jarvis.visualizer import state as visualizer_state
    from jarvis.voice import xtts_client
    from jarvis.voice.wake_word import WakeWordListener

    # Starts the XTTS worker as a genuinely separate OS process (see
    # xtts_client.py / xtts_worker.py) -- NOT xtts_engine.preload_in_background()
    # in-process anymore. That in-process version made torchcodec dlopen
    # the Homebrew-installed FFmpeg's shared libraries into this same
    # process -- which already has faster-whisper's own bundled FFmpeg (via
    # PyAV) loaded -- and macOS's ObjC runtime logged a real class collision
    # (AVFFrameReceiver/AVFAudioReceiver defined in both), warning of
    # "spurious casting failures and mysterious crashes". Wake-word/clap
    # detection stopped firing entirely right after, with no exception or
    # error anywhere -- consistent with silently corrupted audio capture,
    # not a coincidence. Running the model in its own process means that
    # risk, if it recurs at all, can never touch PvRecorder here.
    xtts_client.ensure_worker_started()

    listener = WakeWordListener()
    try:
        while stop_event is None or not stop_event.is_set():
            visualizer_state.publish("idle")
            try:
                trigger = listener.wait(stop_event=stop_event, wake_event=wake_event)
                if trigger is None:
                    break
                _run_active_session(
                    listener, audio.record_utterance, stt.transcribe, tts.speak, stop_event=stop_event
                )
            except Exception as exc:
                print(f"[voice_loop] erro inesperado ({exc!r}) -- reiniciando o microfone", file=sys.stderr)
                try:
                    listener.close()
                except Exception:
                    pass
                time.sleep(1)  # avoids a tight crash-loop if the failure is persistent, not transient
                listener = WakeWordListener()  # lets a genuinely broken mic propagate and end the loop
    finally:
        try:
            listener.close()
        except Exception:
            pass
