"""Record a spoken utterance off the wake-word listener's already-open mic
stream, stopping on a simple RMS-energy silence detector.

No third-party VAD dependency for v1 -- frames are short (32-80ms depending
on the active wake-word engine), so a plain energy threshold is responsive
enough for a personal assistant.
"""

from __future__ import annotations

from array import array

from jarvis.voice.wake_word import WakeWordListener

SILENCE_RMS_THRESHOLD = 300
SILENCE_SECONDS_TO_STOP = 1.3
MAX_UTTERANCE_SECONDS = 9.6


def _rms(frame: list[int]) -> float:
    if not frame:
        return 0.0
    return (sum(sample * sample for sample in frame) / len(frame)) ** 0.5


def record_utterance(listener: WakeWordListener) -> bytes:
    # Frame duration depends on the active wake-word engine (openWakeWord:
    # 80ms/1280 samples; Porcupine: ~32ms/512 samples) -- deriving frame
    # counts from it here, instead of hardcoding them, is what keeps the
    # actual stop/cap durations correct regardless of which engine is active.
    frame_seconds = listener.frame_length / listener.sample_rate
    silence_frames_to_stop = max(1, round(SILENCE_SECONDS_TO_STOP / frame_seconds))
    max_utterance_frames = max(1, round(MAX_UTTERANCE_SECONDS / frame_seconds))

    frames: list[list[int]] = []
    speech_started = False
    silent_frame_count = 0

    for _ in range(max_utterance_frames):
        frame = listener.read_frame()
        frames.append(frame)
        loud = _rms(frame) >= SILENCE_RMS_THRESHOLD

        if loud:
            speech_started = True
            silent_frame_count = 0
        elif speech_started:
            silent_frame_count += 1
            if silent_frame_count >= silence_frames_to_stop:
                break

    samples = array("h")
    for frame in frames:
        samples.extend(frame)
    return samples.tobytes()
