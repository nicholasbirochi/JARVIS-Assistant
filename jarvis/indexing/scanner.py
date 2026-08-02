"""Walks the authorized directories, hashes files, and persists which ones
have already been processed so reruns only touch new/changed files.

Unicode note: on this Mac, at least one real authorized folder ("Currículos")
is stored on disk in NFD (decomposed) form. macOS's own path-lookup layer is
normalization-insensitive, but plain Python dict/string equality is not --
so every path used as a dict/JSON key here goes through normalize_path_key()
first, or a rerun could silently fail to recognize an already-indexed file.
"""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path


def normalize_path_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve()))


def _is_excluded_dir_name(name: str) -> bool:
    from jarvis.config import EXCLUDED_DIR_NAMES

    return name in EXCLUDED_DIR_NAMES or name.endswith(".egg-info")


def _is_excluded_path(path: Path, excluded_paths: list[Path]) -> bool:
    resolved = path.resolve()
    for excluded in excluded_paths:
        excluded_resolved = excluded.resolve()
        if resolved == excluded_resolved or excluded_resolved in resolved.parents:
            return True
    return False


def iter_candidate_files() -> list[Path]:
    # Live lookup (not a top-level import) so tests can monkeypatch
    # jarvis.config.AUTHORIZED_INDEX_ROOTS/EXCLUDED_INDEX_PATHS directly.
    from jarvis.config import AUTHORIZED_INDEX_ROOTS, EXCLUDED_INDEX_PATHS, INDEXABLE_EXTENSIONS

    files: list[Path] = []
    for root in AUTHORIZED_INDEX_ROOTS:
        if not root.exists():
            continue  # e.g. "Estudos/Completed courses" may not exist yet

        for dirpath, dirnames, filenames in os.walk(root):
            current = Path(dirpath)
            if _is_excluded_path(current, EXCLUDED_INDEX_PATHS):
                dirnames[:] = []
                continue
            # Prune in place -- avoids ever descending into vendored/build
            # noise (node_modules, .git, obj/, etc.), not just filtering it
            # out afterwards, which matters when those trees are huge.
            dirnames[:] = [d for d in dirnames if not _is_excluded_dir_name(d)]

            for filename in filenames:
                path = current / filename
                if path.suffix.lower() not in INDEXABLE_EXTENSIONS:
                    continue
                if _is_excluded_path(path, EXCLUDED_INDEX_PATHS):
                    continue
                files.append(path)
    return files


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class FileRecord:
    hash: str
    size: int
    mtime: float
    last_processed_at: str | None


def load_index_state(path: Path) -> dict[str, FileRecord]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {key: FileRecord(**value) for key, value in raw.items()}


def save_index_state(path: Path, state: dict[str, FileRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {key: asdict(record) for key, record in state.items()}
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def diff_against_state(files: list[Path], state: dict[str, FileRecord]) -> list[Path]:
    """New/changed files, by content hash -- not mtime alone, since OneDrive
    sync churn makes mtime unreliable as a change signal on its own.

    A file that isn't locally materialized yet (OneDrive Files On-Demand
    placeholder, sync paused, transient network blip) can time out just
    trying to read it -- treat that as "needs (re)processing" rather than
    crashing the whole run; extract.extract_text() will independently and
    gracefully flag it as unreadable if it's still unavailable when actually
    read."""
    changed: list[Path] = []
    for path in files:
        key = normalize_path_key(path)
        existing = state.get(key)
        try:
            current_hash = file_hash(path)
        except OSError:
            changed.append(path)
            continue
        if existing is None or existing.hash != current_hash:
            changed.append(path)
    return changed
