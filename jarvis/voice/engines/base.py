"""Common interface both wake-word engines implement, so WakeWordListener
and audio.py never need to know which one is active."""

from __future__ import annotations

from typing import Protocol


class WakeWordEngine(Protocol):
    @property
    def frame_length(self) -> int:
        """Samples expected per process() call."""
        ...

    @property
    def sample_rate(self) -> int:
        """Always 16000 for both current engines."""
        ...

    def process(self, frame: list[int]) -> bool:
        """Returns True the instant the wake word is detected in this frame."""
        ...

    def close(self) -> None: ...
