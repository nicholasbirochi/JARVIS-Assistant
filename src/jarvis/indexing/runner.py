"""Orchestrates scan -> diff -> extract -> propose -> write one proposal
file. Bounded per run (INDEX_MAX_FILES_PER_RUN) since a single authorized
root alone can have dozens of subfolders and each file may cost a real
local-model call -- rerunning drains the backlog via index_state.json, no
mid-run resumability engineering needed. Index state only updates for files
whose proposal was actually written, so an interrupted run loses nothing
already-committed."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from jarvis.indexing import extract
from jarvis.indexing import scanner
from jarvis.indexing.proposals import Proposal
from jarvis.resume import store
from jarvis.resume.schema import Resume
from jarvis.indexing import proposer


def run(resume: Resume | None = None, limit: int | None = None) -> Path | None:
    # Live lookups (not top-level imports/bound defaults) so tests can
    # monkeypatch jarvis.config.* directly.
    from jarvis.config import INDEX_MAX_FILES_PER_RUN, INDEX_STATE_PATH, PROPOSALS_DIR

    limit = limit if limit is not None else INDEX_MAX_FILES_PER_RUN
    resume = resume or store.load()
    state = scanner.load_index_state(INDEX_STATE_PATH)

    candidates = scanner.iter_candidate_files()
    to_process = scanner.diff_against_state(candidates, state)[:limit]
    if not to_process:
        return None

    changes = []
    unreadable = []
    for path in to_process:
        try:
            text = extract.extract_text(path)
        except OSError:
            # File couldn't be accessed at all (OneDrive placeholder not
            # materialized, transient network issue, etc.) -- distinct from
            # "read fine, no text layer". Flag it and skip straight to the
            # next file without touching index_state, so it's retried on
            # the next run instead of being recorded as permanently
            # unreadable.
            unreadable.append(
                proposer.unreadable_file_entry(path, reason="falha de leitura (tentar novamente)")
            )
            continue

        already_flagged_unreadable = text is None
        if already_flagged_unreadable:
            unreadable.append(proposer.unreadable_file_entry(path))
        else:
            batch = proposer.propose_changes_for_file(path, text, resume)
            changes.extend(proposer.attach_evidence(batch, path, text, resume))

        try:
            key = scanner.normalize_path_key(path)
            state[key] = scanner.FileRecord(
                hash=scanner.file_hash(path),
                size=path.stat().st_size,
                mtime=path.stat().st_mtime,
                last_processed_at=datetime.now(timezone.utc).isoformat(),
            )
        except OSError:
            # Still unavailable (OneDrive placeholder not materialized,
            # transient network issue, etc.) -- don't record it as
            # processed, so it's retried on the next run instead of being
            # silently skipped forever.
            if not already_flagged_unreadable:
                unreadable.append(proposer.unreadable_file_entry(path))

    proposal = Proposal(
        created_at=datetime.now(timezone.utc).isoformat(),
        source_files=[scanner.normalize_path_key(p) for p in to_process],
        changes=proposer.dedupe_update_field_changes(changes),
        unreadable_files=unreadable,
    )

    PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = PROPOSALS_DIR / f"proposal_{stamp}.json"
    out_path.write_text(
        json.dumps(proposal.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    scanner.save_index_state(INDEX_STATE_PATH, state)
    return out_path
