"""Central configuration: paths, secrets, model IDs, and the one exact-phrase
constant that must never be paraphrased by the LLM."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# Quiet by design: this runs as a background listener, not a dev tool, so
# library log/progress noise (huggingface_hub download bars, openwakeword's
# "tried to import tflite runtime" notice, etc.) has nowhere useful to go.
# Must be set before those libraries are imported, which is why this lives
# at the top of config.py -- everything else imports config first.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
logging.getLogger().setLevel(logging.ERROR)

PICOVOICE_ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY")

DATA_DIR = PROJECT_ROOT / "data"
RESUME_PATH = DATA_DIR / "resume.json"
RESUME_SCHEMA_PATH = DATA_DIR / "resume.schema.json"
BACKUPS_DIR = DATA_DIR / "backups"
REVIEW_DIR = DATA_DIR / "review"

# Local LLM served by Ollama (https://ollama.com) -- no cloud API, no API key.
# `ollama pull` the model once via CLI before first use; see README.md.
# LLM_PROVIDER selects the LocalLLMProvider implementation (jarvis/assistant/providers.py);
# only "ollama" exists today, kept configurable so a future MLXProvider slots in cleanly.
LLM_PROVIDER = os.environ.get("JARVIS_LLM_PROVIDER", "ollama")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
LOCAL_MODEL = os.environ.get("JARVIS_MODEL", "qwen2.5:14b")

# Spoken the instant a trigger fires, before the model is ever invoked -- an
# LLM asked to "say this greeting" could paraphrase or drop the punctuation,
# which isn't acceptable for a phrase the user specified verbatim. Each
# trigger has its own exact phrase.
GREETING = "Seja bem-vindo, Senhor Nicholas... vamos começar o trabalho!"
CLAP_GREETING = "Olá, Nicolas, vamos começar o trabalho!"

# "Felipe (Aprimorada)" -- com.apple.voice.enhanced.pt-BR.Felipe -- is a
# proper Enhanced-quality male pt_BR voice (downloaded via System Settings >
# Accessibility > Spoken Content > System Voice; NOT preinstalled). Same
# voice family/engine as "Luciana" (com.apple.voice.compact.pt-BR.Luciana,
# the good-quality default female alternative), unlike the male-sounding
# names macOS ships out of the box (Eddy, Flo, Grandpa, Reed, Rocko...),
# which all run on the old, noticeably robotic "Eloquence" engine
# (com.apple.eloquence.pt-BR.*). Siri voices (com.apple.siri.natural.*,
# picked in the same Settings screen's separate "Siri Voice" picker) look
# similar but are NOT usable here at all -- confirmed unreachable via `say`
# and via AVSpeechSynthesisVoice directly, not just the CLI; Apple doesn't
# expose them to third-party code.
#
# Using the full stable identifier, not the display name, is deliberate:
# these persona-style names exist identically across every language
# Eloquence supports, so passing just "Eddy" (or even "Felipe") to `say -v`
# doesn't reliably resolve to the pt_BR one. Find installed identifiers with:
#   python -c "from AVFoundation import AVSpeechSynthesisVoice as V; [print(v.name(), v.identifier(), v.quality()) for v in V.speechVoices() if v.language()=='pt-BR']"
TTS_VOICE = os.environ.get("TTS_VOICE", "com.apple.voice.enhanced.pt-BR.Felipe")
WAKE_WORD = "jarvis"
STOP_PHRASES = ("tchau jarvis", "tchau, jarvis", "obrigado jarvis", "encerrar")

# "openwakeword" (default, no account/key -- ships a pretrained "hey jarvis"
# model) or "porcupine" (optional adapter, needs PICOVOICE_ACCESS_KEY).
WAKE_WORD_ENGINE = os.environ.get("WAKE_WORD_ENGINE", "openwakeword")

# Two claps is a second, independent activation trigger that always runs
# alongside the wake-word engine above (see jarvis/voice/engines/clap_detector.py).
# Peak amplitude, not RMS -- a clap's transient is a few ms long and RMS
# over an 80ms frame dilutes it too much to reliably cross a threshold.
# Amplitude-based detection is more environment-sensitive than the neural
# wake-word engines, so the threshold is a tunable env var, not fixed in code.
# Default lowered from 6000: a moderate clap at normal laptop-mic distance
# was empirically observed to often peak well below that. Run
# `python -m jarvis calibrate-claps` to see real peak values for your own
# mic/room and set this precisely instead of guessing.
CLAP_ACTIVATION_ENABLED = os.environ.get("CLAP_ACTIVATION_ENABLED", "true").lower() != "false"
CLAP_PEAK_THRESHOLD = float(os.environ.get("CLAP_PEAK_THRESHOLD", "3500"))
CLAP_WINDOW_SECONDS = float(os.environ.get("CLAP_WINDOW_SECONDS", "1.5"))

WHISPER_MODEL_SIZE = "small"
WHISPER_LANGUAGE = "pt"

SOURCE_RESUME_DOCS = [
    "/Users/nicholasbirochi/Library/CloudStorage/OneDrive-FundaçãoSalvadorArena/Extras/Perfil/Currículos/Currículo - DataBase - Brasil ATS.docx",
    "/Users/nicholasbirochi/Library/CloudStorage/OneDrive-FundaçãoSalvadorArena/Extras/Perfil/Currículos/Currículo - DataBase - International ATS.docx",
]

# Incremental document indexer (jarvis/indexing/) -- only these roots are ever
# scanned; the project's own repo is explicitly excluded so code/README never
# get mistaken for résumé projects.
_ONEDRIVE_ROOT = "/Users/nicholasbirochi/Library/CloudStorage/OneDrive-FundaçãoSalvadorArena"
AUTHORIZED_INDEX_ROOTS = [
    Path(f"{_ONEDRIVE_ROOT}/Extras/Perfil/Currículos"),
    Path(f"{_ONEDRIVE_ROOT}/Estudos/Completed courses"),
    Path(f"{_ONEDRIVE_ROOT}/Estudos/Projetos"),
]
EXCLUDED_INDEX_PATHS = [
    Path(f"{_ONEDRIVE_ROOT}/Estudos/Projetos/54 - J.A.R.V.I.S"),
]
INDEXABLE_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
# Vendored/build noise inside project folders -- not the user's own writing,
# and would otherwise drown out real project READMEs in every indexing run.
EXCLUDED_DIR_NAMES = {
    "node_modules", ".git", ".venv", "venv", "__pycache__", "obj", "bin",
    "dist", "build", ".next", "target", ".pytest_cache", "egg-info",
}
INDEX_STATE_PATH = DATA_DIR / "index_state.json"
PROPOSALS_DIR = DATA_DIR / "proposals"
INDEX_MAX_FILES_PER_RUN = 20

# Site adapters (jarvis/sites/) -- Playwright-driven, one persistent browser
# session per site, saved under SITES_STATE_DIR (cookies -- never commit;
# see .gitignore). Login is always a manual, one-time step in a real,
# visible browser window (jarvis/sites/session.py) -- no password ever
# passes through this code. Domains verified against Gupy's own public
# pages (WebFetch), not guessed.
SITES_STATE_DIR = DATA_DIR / "sites"
GUPY_LOGIN_URL = "https://login.gupy.io/candidates/signin"
GUPY_PORTAL_URL = "https://portal.gupy.io/"
# Headless by default so a normal `preview`/`apply` run doesn't pop a window;
# `login` always forces headed regardless, since it needs a human present.
SITES_HEADLESS = os.environ.get("SITES_HEADLESS", "true").lower() != "false"
