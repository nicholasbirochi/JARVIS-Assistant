"""Second, independent activation trigger: two hand claps. Not a
WakeWordEngine (it doesn't use a neural wake-word model at all -- just
rising-edge amplitude detection on the same mic frames), so it's driven
alongside the primary engine by WakeWordListener rather than selected via
WAKE_WORD_ENGINE.

Amplitude-based clap detection is inherently more environment-sensitive
than the neural-net wake-word engines (mic gain, distance, room noise all
shift what "loud" means) -- CLAP_RMS_THRESHOLD is deliberately a tunable
config constant, not a hardcoded one, so it can be adjusted without a code
change if it's too trigger-happy or too insensitive in practice.
"""

from __future__ import annotations


def _rms(frame: list[int]) -> float:
    if not frame:
        return 0.0
    return (sum(sample * sample for sample in frame) / len(frame)) ** 0.5


class ClapDetector:
    def __init__(
        self,
        threshold: float | None = None,
        clap_window_seconds: float | None = None,
        min_gap_seconds: float = 0.1,
    ) -> None:
        from jarvis.config import CLAP_RMS_THRESHOLD, CLAP_WINDOW_SECONDS

        self._threshold = threshold if threshold is not None else CLAP_RMS_THRESHOLD
        self._clap_window_seconds = (
            clap_window_seconds if clap_window_seconds is not None else CLAP_WINDOW_SECONDS
        )
        self._min_gap_seconds = min_gap_seconds
        self._was_loud = False
        self._elapsed = 0.0
        self._first_clap_at: float | None = None

    def process(self, frame: list[int], frame_seconds: float) -> bool:
        """Feed one frame; returns True the instant a second clap lands
        within the window of the first. `frame_seconds` is the duration of
        this frame -- passed in rather than assumed, since it depends on
        whichever WakeWordEngine's frame_length/sample_rate is active."""
        self._elapsed += frame_seconds
        loud = _rms(frame) >= self._threshold

        # Rising-edge only: a clap's reverb/decay can span a couple of
        # frames, and counting every still-loud frame would register one
        # physical clap as several.
        is_onset = loud and not self._was_loud
        self._was_loud = loud

        if not is_onset:
            return False

        if self._first_clap_at is None:
            self._first_clap_at = self._elapsed
            return False

        gap = self._elapsed - self._first_clap_at
        if gap < self._min_gap_seconds:
            return False  # too close -- almost certainly the same clap's echo

        if gap <= self._clap_window_seconds:
            self._first_clap_at = None
            return True

        # Too far apart to count as a pair -- this onset starts a new attempt.
        self._first_clap_at = self._elapsed
        return False
