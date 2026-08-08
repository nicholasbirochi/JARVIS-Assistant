"""Pub/sub broadcaster for the visualizer's live state. conversation.py
calls publish() at each real state transition; server.py's SSE endpoint
subscribes and fans events out to however many browser tabs are open.
Deliberately in-process/thread-based, not a message broker -- this is a
single-machine, single-user visual aid, not a distributed system."""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass
from typing import Literal

State = Literal["idle", "listening", "speaking"]

_VALID_STATES = ("idle", "listening", "speaking")


@dataclass(frozen=True)
class StateEvent:
    state: State
    text: str = ""


_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_current = StateEvent(state="idle")


def current() -> StateEvent:
    with _lock:
        return _current


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


def subscribe() -> "queue.Queue[StateEvent]":
    q: "queue.Queue[StateEvent]" = queue.Queue()
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q: "queue.Queue[StateEvent]") -> None:
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)
