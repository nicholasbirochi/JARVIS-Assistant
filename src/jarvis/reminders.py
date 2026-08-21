"""Simple personal reminders JARVIS can take by voice/text and read back
later -- not résumé data (jarvis/resume/), not a code decision (see
jarvis/roadmap.py for that). Stored as a flat JSON list under DATA_DIR,
gitignored (mutable personal notes, not code) but fine living inside the
OneDrive-synced project folder like the other data/ files -- nothing
here is a secret the way site session cookies (LOCAL_STATE_DIR) are.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _reminders_path():
    from jarvis.config import DATA_DIR  # live lookup -- monkeypatchable in tests

    return DATA_DIR / "reminders.json"


def _load() -> list[dict]:
    path = _reminders_path()
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []  # a corrupt file must never crash a reminder read/add -- treat as empty


def _save(reminders: list[dict]) -> None:
    path = _reminders_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reminders, ensure_ascii=False, indent=2), encoding="utf-8")


def add_reminder(text: str) -> dict:
    reminders = _load()
    entry = {"text": text, "created_at": datetime.now(timezone.utc).isoformat()}
    reminders.append(entry)
    _save(reminders)
    return entry


def list_reminders() -> list[dict]:
    return _load()
