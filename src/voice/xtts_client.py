"""Client for the isolated XTTS synthesis worker (xtts_worker.py) -- talks
plain HTTP to 127.0.0.1, and spawns the worker subprocess if it isn't
already running. tts.py uses this instead of xtts_engine.py directly; see
xtts_engine.py's module docstring for why synthesis runs out-of-process
at all."""

from __future__ import annotations

import atexit
import json
import struct
import subprocess
import urllib.error
import urllib.request

_process: "subprocess.Popen | None" = None
_log_file = None  # kept open for the life of the process -- closing it would break the redirect


def has_reference_audio() -> bool:
    from voice import xtts_engine

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

    from config import LOCAL_STATE_DIR, PROJECT_ROOT

    log_dir = LOCAL_STATE_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    _log_file = open(log_dir / "xtts_worker.log", "a", encoding="utf-8")

    # Deliberately NOT sys.executable -- confirmed live that it doesn't
    # reliably mean "a python that can import voice.xtts_worker". Under the
    # packaged JARVIS.app (py2app alias mode), sys.executable resolves to
    # the raw Homebrew framework interpreter (py2app's stub dlopens it
    # directly), which has no idea this project's venv/site-packages .pth
    # file even exist -- the worker subprocess spawned that way failed
    # every time with "ModuleNotFoundError", silently falling back to the
    # non-cloned voice. The project's own venv python is the one
    # interpreter guaranteed to have src/ on sys.path (via the .pth file
    # -- see README), regardless of how *this* process itself was
    # launched.
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    _process = subprocess.Popen(
        [str(venv_python), "-m", "voice.xtts_worker"],
        cwd=PROJECT_ROOT / "src",
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
    from config import XTTS_WORKER_PORT

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{XTTS_WORKER_PORT}/health", timeout=1) as resp:
            return json.loads(resp.read())["ready"]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return False  # worker not up yet, still loading, or genuinely gone -- all "not ready"


def synthesize_to_file(text: str, out_path: str) -> None:
    """Raises on any failure (worker unreachable, not ready, synthesis
    error) -- callers (tts.py) must check is_ready() first and treat this
    as a call that can fail, same contract as xtts_engine.synthesize_to_file."""
    from config import XTTS_WORKER_PORT

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


def _read_exact(resp, n: int) -> bytes:
    data = b""
    while len(data) < n:
        piece = resp.read(n - len(data))
        if not piece:
            raise urllib.error.URLError("conexão encerrada no meio do streaming de áudio")
        data += piece
    return data


def synthesize_stream(text: str):
    """Yields raw PCM chunks (int16, mono, xtts_engine.STREAM_SAMPLE_RATE
    Hz) as they arrive from the worker -- the caller (tts.py) can start
    playing audio before the whole utterance has even finished generating,
    instead of synthesize_to_file's wait-for-everything behavior.

    Raises on any failure that happens before the first chunk (worker
    unreachable, not ready, synthesis error before any audio was
    produced) -- same "callers must check is_ready() first" contract as
    synthesize_to_file. Once at least one chunk has been yielded, a later
    failure just ends the generator instead of raising -- see tts.py's
    caller for why: audio may already be playing by then, so falling back
    to a different voice mid-sentence would be worse than just stopping."""
    from config import XTTS_WORKER_PORT

    body = json.dumps({"text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"http://127.0.0.1:{XTTS_WORKER_PORT}/synthesize_stream",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    try:
        while True:
            (chunk_len,) = struct.unpack(">I", _read_exact(resp, 4))
            if chunk_len == 0:
                return
            yield _read_exact(resp, chunk_len)
    finally:
        resp.close()
