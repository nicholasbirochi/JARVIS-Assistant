from voice import audio


class FakeListener:
    """Stands in for WakeWordListener: first frame is loud, everything after
    is silent, forever -- exercises the silence-to-stop path."""

    def __init__(self, frame_length: int, sample_rate: int = 16000):
        self.frame_length = frame_length
        self.sample_rate = sample_rate
        self.call_count = 0

    def read_frame(self):
        self.call_count += 1
        if self.call_count == 1:
            return [10_000] * self.frame_length
        return [0] * self.frame_length


class AlwaysLoudListener:
    def __init__(self, frame_length: int, sample_rate: int = 16000):
        self.frame_length = frame_length
        self.sample_rate = sample_rate
        self.call_count = 0

    def read_frame(self):
        self.call_count += 1
        return [10_000] * self.frame_length


def test_record_utterance_stops_at_same_wall_clock_duration_regardless_of_frame_length():
    porcupine_like = FakeListener(frame_length=512)   # ~32ms/frame
    openwakeword_like = FakeListener(frame_length=1280)  # 80ms/frame

    audio.record_utterance(porcupine_like)
    audio.record_utterance(openwakeword_like)

    porcupine_seconds = porcupine_like.call_count * (512 / 16000)
    oww_seconds = openwakeword_like.call_count * (1280 / 16000)

    # Both should land near SILENCE_SECONDS_TO_STOP regardless of frame_length
    # -- this is the concrete regression test for the frame-count/duration bug.
    assert abs(porcupine_seconds - oww_seconds) < 0.15
    assert abs(porcupine_seconds - audio.SILENCE_SECONDS_TO_STOP) < 0.2


def test_record_utterance_respects_max_utterance_cap():
    listener = AlwaysLoudListener(frame_length=1280)

    result = audio.record_utterance(listener)

    seconds_recorded = listener.call_count * (1280 / 16000)
    assert abs(seconds_recorded - audio.MAX_UTTERANCE_SECONDS) < 0.2
    assert len(result) == listener.call_count * 1280 * 2  # 16-bit samples -> 2 bytes each


def test_record_utterance_returns_concatenated_pcm16_bytes():
    listener = FakeListener(frame_length=512)

    result = audio.record_utterance(listener)

    assert isinstance(result, bytes)
    assert len(result) == listener.call_count * 512 * 2
