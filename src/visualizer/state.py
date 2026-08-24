"""Pub/sub broadcaster for the visualizer's live state. conversation.py
calls publish() at each real state transition; server.py's SSE endpoint
subscribes and fans events out to however many browser tabs are open.
Deliberately in-process/thread-based, not a message broker -- this is a
single-machine, single-user visual aid, not a distributed system.

publish_data()/current_data()/clear_data() are a second, independent
channel on the same pub/sub plumbing -- structured chart/analysis
payloads (finance.py, job_search.py) rather than the
listening/thinking/speaking state machine above. Deliberately NOT folded
into StateEvent: a chart has its own lifecycle (stays on screen until
replaced or explicitly cleared), independent of whichever
listening/thinking/speaking transition happens to fire next -- bundling
them would mean every unrelated publish("listening") call elsewhere in
the codebase would need to remember to carry the last chart forward or
it'd flicker away."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Any, Literal, Union

State = Literal["off", "idle", "listening", "thinking", "speaking"]

_VALID_STATES = ("off", "idle", "listening", "thinking", "speaking")


@dataclass(frozen=True)
class StateEvent:
    state: State
    text: str = ""


@dataclass(frozen=True)
class DataEvent:
    """kind identifies the chart shape to the frontend (e.g. "finance",
    "jobs" -- see page.html's renderChart()); an empty kind is the
    "clear the chart" signal, published by clear_data()."""

    kind: str
    payload: dict[str, Any]


Event = Union[StateEvent, DataEvent]

_lock = threading.Lock()
_subscribers: list["queue.Queue[Event]"] = []
# "off" (not "idle") by default -- before the menu bar's toggle has ever
# been clicked, or once it's turned off, JARVIS genuinely isn't listening
# for anything. "idle" specifically means the voice loop IS running and
# waiting for the wake word -- run_voice_loop only ever publishes "idle",
# never "off"; only the menu bar (menubar.py) publishes "off",
# since it's the only thing that actually knows the loop was stopped
# rather than just between wake-word sessions.
_current = StateEvent(state="off")
_current_data: DataEvent | None = None


def current() -> StateEvent:
    with _lock:
        return _current


def current_data() -> DataEvent | None:
    return _current_data


def publish(state: State, text: str = "") -> None:
    if state not in _VALID_STATES:
        raise ValueError(f"estado inválido: {state!r} (esperado um de {_VALID_STATES})")

    global _current
    event = StateEvent(state=state, text=text)
    with _lock:
        _current = event
        subscribers = list(_subscribers)
    for q in subscribers:
        q.put(event)


def publish_data(kind: str, payload: dict[str, Any]) -> None:
    """Pushes a chart/analysis payload to every open HUD window. Best-
    effort by design at the call site (assistant/tools.py wraps
    this in a try/except) -- a visualization failing must never break the
    actual spoken/text answer it's illustrating."""
    global _current_data
    event = DataEvent(kind=kind, payload=payload)
    with _lock:
        _current_data = event
        subscribers = list(_subscribers)
    for q in subscribers:
        q.put(event)


def clear_data() -> None:
    global _current_data
    event = DataEvent(kind="", payload={})
    with _lock:
        _current_data = None
        subscribers = list(_subscribers)
    for q in subscribers:
        q.put(event)


def subscribe() -> "queue.Queue[Event]":
    q: "queue.Queue[Event]" = queue.Queue()
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: "queue.Queue[Event]") -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)
