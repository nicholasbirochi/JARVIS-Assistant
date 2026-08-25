"""A durable, local record of which job listings Nicholas has actually,
successfully submitted a real application for (ApplicationPreview.
submitted == True) -- kept across restarts, unlike the in-memory-only
preview object each individual apply call returns. Solves a real,
recurring gap: the job portal (job_portal/server.py) re-fetches and
re-renders listings on every search and every process restart, with no
memory of "I already applied here" -- Nicholas asked for the portal to
show that directly ("mostrar as vagas que eu já me inscrevi").

Not confidential (no PII, no site credentials -- just "this URL was
applied to, at this time"), so this lives under DATA_DIR like the rest
of the portal's own cache (job_matches/), not LOCAL_STATE_DIR.

File format: a flat JSON object keyed by the job's own URL (the same
identifier the portal/adapters already use everywhere), mapping to
{"site_name": ..., "submitted_at": <ISO 8601 UTC>}. Read fresh on every
use, write-whole-file on every update -- this is a small, low-frequency
log (one write per real submission), not something that needs a
database or append-only format."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def applications_log_path() -> Path:
    from config import DATA_DIR

    return DATA_DIR / "applications_sent.json"


def load_applications_log() -> dict[str, dict]:
    """Reads applications_log_path() and returns the {url: {...}} map.
    A missing or unreadable file just comes back {} -- not having
    submitted anything yet is the normal starting state, never an
    error. Never raises."""
    path = applications_log_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_application(url: str, site_name: str) -> None:
    """Marks `url` as successfully, really submitted -- called only
    right after an ApplicationPreview comes back with submitted=True
    (see assistant/tools.py's continue_job_application()), never
    speculatively. Overwrites any prior entry for the same URL with a
    fresh timestamp -- a real re-submission (rare, but not impossible if
    Nicholas explicitly retries) should update "quando", not be
    silently ignored."""
    path = applications_log_path()
    log = load_applications_log()
    log[url] = {
        "site_name": site_name,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
