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
{"site_name": ..., "submitted_at": <ISO 8601 UTC>, "source": ...}. Read
fresh on every use, write-whole-file on every update -- this is a
small, low-frequency log (one write per real submission), not
something that needs a database or append-only format.

"source" (2026-09-07, "me candidatei a todas as vagas de banco e as
Fintechs!... menos, das vagas da remoteok" -- Nicholas told JARVIS,
after the fact, that he'd applied to a batch of real listings by hand,
outside any automated flow): distinguishes "jarvis" (the only kind that
existed before this date -- continue_job_application() actually drove
the browser and clicked the real submit button) from "manual" (Nicholas
applied himself; JARVIS is just recording what he reported, not what it
verified). Both are equally real submissions -- the field exists so the
portal/analysis screen can be honest about which kind of evidence
backs each one, not to imply "manual" is less trustworthy."""

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


def record_application(url: str, site_name: str, *, source: str = "jarvis") -> None:
    """Marks `url` as successfully, really submitted -- called either
    right after an ApplicationPreview comes back with submitted=True
    (see assistant/tools.py's continue_job_application(), source=
    "jarvis", the default), or when Nicholas reports he applied to a
    listing himself outside any automated flow (source="manual" --
    see mark_manual_applications.py-style one-off scripts). Never
    speculative either way -- only called for a submission that really
    happened. Overwrites any prior entry for the same URL with a fresh
    timestamp -- a real re-submission (rare, but not impossible) should
    update "quando", not be silently ignored."""
    path = applications_log_path()
    log = load_applications_log()
    log[url] = {
        "site_name": site_name,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
