"""Client for the isolated XTTS synthesis worker (xtts_worker.py) -- talks
plain HTTP to 127.0.0.1, and spawns the worker subprocess if it isn't
already running. tts.py uses this instead of xtts_engine.py directly; see
xtts_engine.py's module docstring for why synthesis runs out-of-process
at all."""

from __future__ import annotations

import atexit
import json
import subprocess
import sys
import urllib.error
import urllib.request

_process: "subprocess.Popen | None" = None
_log_file = None  # kept open for the life of the process -- closing it would break the redirect


def has_reference_audio() -> bool:
    from jarvis.voice import xtts_engine

    return xtts_engine.has_reference_audio()


def ensure_worker_started() -> None:
    """Spawns the worker subprocess, at most once per process. No-ops if
    there's no reference clip yet -- no point starting a whole separate
    Python process (and paying the model's real memory footprint) for a
    voice that can't clone anything. Safe to call repeatedly."""
    global _process, _log_file

    if not has_reference_audio():
        return
    if _process is not None and _process.poll() is None:
        return

    from jarvis.config import LOCAL_STATE_DIR

    log_dir = LOCAL_STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = open(log_dir / "xtts_worker.log", "a", encoding="utf-8")

    _process = subprocess.Popen(
        [sys.executable, "-m", "jarvis.voice.xtts_worker"],
        stdout=_log_file,
        stderr=_log_file,
    )
    # Best-effort cleanup on normal interpreter exit -- a subprocess.Popen
    # child doesn't die on its own just because the parent does.
    atexit.register(_terminate_worker)


def _terminate_worker() -> None:
    if _process is not None and _process.poll() is None:
        _process.terminate()


def is_ready() -> bool:
    from jarvis.config import XTTS_WORKER_PORT

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{XTTS_WORKER_PORT}/health", timeout=1) as resp:
            return json.loads(resp.read())["ready"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return False  # worker not up yet, still loading, or genuinely gone -- all "not ready"


def synthesize_to_file(text: str, out_path: str) -> None:
    """Raises on any failure (worker unreachable, not ready, synthesis
    error) -- callers (tts.py) must check is_ready() first and treat this
    as a call that can fail, same contract as xtts_engine.synthesize_to_file."""
    from jarvis.config import XTTS_WORKER_PORT

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{XTTS_WORKER_PORT}/synthesize",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(out_path, "wb") as f:
        f.write(data)
