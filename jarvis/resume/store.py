"""Load/save/edit the canonical resume.json.

Every write re-validates the *whole* resume against the pydantic schema before
touching disk, and every write is preceded by a timestamped backup -- a voice
transcript is a noisier input source than a form, so we treat every edit as
something that might need to be rolled back by hand. Every applied change
(via update_field/append_item) also lands in change_log -- the audit trail.
"""

from __future__ import annotations

import copy
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from jarvis.config import BACKUPS_DIR, RESUME_PATH
from jarvis.resume.schema import Conflict, Resume


class FieldPathError(ValueError):
    """Raised when a dot-path doesn't resolve inside the resume structure."""


def coerce_value(value: str) -> Any:
    """Turns a plain string into whatever JSON type it represents -- used
    wherever a value arrives as a string by necessity (voice tool-calling,
    LLM structured-output slots that need a concrete `string` JSON-schema
    type to reliably get filled in at all, rather than an unconstrained
    `Any`) but might actually mean a bool/number/list (e.g. "true", "42",
    '["a", "b"]"). Falls back to the raw string when it isn't valid JSON."""
    try:
        return json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return value


def load(path: Path | None = None) -> Resume:
    path = path or RESUME_PATH
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Resume.model_validate(data)


def save(resume: Resume, path: Path | None = None) -> None:
    path = path or RESUME_PATH
    if path.exists():
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy2(path, BACKUPS_DIR / f"resume.{stamp}.json")

    resume.meta.last_updated = datetime.now(timezone.utc).isoformat()

    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(resume.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _split_path(field_path: str) -> list[str]:
    segments = field_path.split(".")
    if not segments or any(s == "" for s in segments):
        raise FieldPathError(f"Malformed field path: {field_path!r}")
    return segments


def _navigate_to(container: Any, segments: list[str]) -> Any:
    """Walk every segment, returning the node it points at."""
    node = container
    for seg in segments:
        if isinstance(node, list):
            if not seg.lstrip("-").isdigit():
                raise FieldPathError(f"Expected list index, got {seg!r}")
            idx = int(seg)
            if not (-len(node) <= idx < len(node)):
                raise FieldPathError(f"List index out of range: {seg!r}")
            node = node[idx]
        elif isinstance(node, dict):
            if seg not in node:
                raise FieldPathError(f"Unknown field: {seg!r}")
            node = node[seg]
        else:
            raise FieldPathError(f"Cannot descend into {type(node).__name__} at {seg!r}")
    return node


def _navigate(container: Any, segments: list[str]) -> tuple[Any, str]:
    """Walk all but the last segment, returning (parent_container, last_key)."""
    return _navigate_to(container, segments[:-1]), segments[-1]


def get_field(resume: Resume, field_path: str) -> Any:
    segments = _split_path(field_path)
    data = resume.model_dump(mode="json")
    parent, last = _navigate(data, segments)
    if isinstance(parent, list):
        if not last.lstrip("-").isdigit():
            raise FieldPathError(f"Expected list index, got {last!r}")
        idx = int(last)
        if not (-len(parent) <= idx < len(parent)):
            raise FieldPathError(f"List index out of range: {last!r}")
        return parent[idx]
    if isinstance(parent, dict):
        if last not in parent:
            raise FieldPathError(f"Unknown field: {last!r}")
        return parent[last]
    raise FieldPathError(f"Cannot read {last!r} from {type(parent).__name__}")


def _append_change_record(
    data: dict, field_path: str, old_value: Any, new_value: Any, source: str, note: str | None
) -> None:
    data.setdefault("change_log", []).append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "field_path": field_path,
            "old_value": old_value,
            "new_value": new_value,
            "source": source,
            "note": note,
        }
    )


def update_field(
    resume: Resume,
    field_path: str,
    value: Any,
    *,
    source: str = "manual_review",
    note: str | None = None,
) -> Resume:
    """Return a NEW, re-validated Resume with `field_path` set to `value`,
    recording the change in change_log.

    Raises FieldPathError for a bad path, or pydantic.ValidationError if the
    resulting resume would be invalid -- either way, the caller's original
    `resume` object is left untouched (nothing is saved here).
    """
    old_value = get_field(resume, field_path)  # validates the path up front too
    segments = _split_path(field_path)
    data = copy.deepcopy(resume.model_dump(mode="json"))
    parent, last = _navigate(data, segments)

    if isinstance(parent, list):
        if not last.lstrip("-").isdigit():
            raise FieldPathError(f"Expected list index, got {last!r}")
        idx = int(last)
        if not (-len(parent) <= idx < len(parent)):
            raise FieldPathError(f"List index out of range: {last!r}")
        parent[idx] = value
    elif isinstance(parent, dict):
        if last not in parent:
            raise FieldPathError(f"Unknown field: {last!r}")
        parent[last] = value
    else:
        raise FieldPathError(f"Cannot set {last!r} on {type(parent).__name__}")

    _append_change_record(data, field_path, old_value, value, source, note)
    return Resume.model_validate(data)


def append_item(
    resume: Resume,
    list_field_path: str,
    item: dict,
    *,
    source: str = "manual_review",
    note: str | None = None,
) -> Resume:
    """Appends `item` to the list field at `list_field_path` (e.g.
    "certifications"), recording the change in change_log. Unlike
    update_field, which can only set an existing key/index, this is how a
    brand-new item (a newly found certificate, project, etc.) gets added."""
    data = copy.deepcopy(resume.model_dump(mode="json"))
    node = _navigate_to(data, _split_path(list_field_path))
    if not isinstance(node, list):
        raise FieldPathError(f"{list_field_path!r} não é uma lista")

    new_index = len(node)
    node.append(item)
    _append_change_record(data, f"{list_field_path}.{new_index}", None, item, source, note)
    return Resume.model_validate(data)


def register_conflict(resume: Resume, conflict: Conflict) -> Resume:
    """Appends `conflict` to resume.conflicts -- registered independent of
    how (or whether) it gets resolved, since "two sources disagreed and a
    human looked at it" is itself audit-worthy."""
    data = copy.deepcopy(resume.model_dump(mode="json"))
    data.setdefault("conflicts", []).append(conflict.model_dump(mode="json"))
    return Resume.model_validate(data)
