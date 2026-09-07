"""Central configuration: paths, secrets, model IDs, and the one exact-phrase
constant that must never be paraphrased by the LLM."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# PROJECT_ROOT itself lives inside an actively-synced OneDrive folder (the
# user's whole "Estudos/Projetos" tree is under OneDrive-<org>/). That's
# fine for résumé data -- it's meant to end up in job-site profiles anyway,
# and the schema deliberately excludes CPF/RG/address/birth date. It is NOT
# fine for live site-adapter auth cookies or anything that can incidentally
# show sensitive fields (a full profile-page screenshot) -- those must never
# leave this machine, and OneDrive sync would silently defeat that. Anything
# in that category goes under LOCAL_STATE_DIR instead, outside PROJECT_ROOT
# and outside any cloud-sync tree, never DATA_DIR.
LOCAL_STATE_DIR = Path(
    os.environ.get("JARVIS_LOCAL_STATE_DIR", str(Path.home() / "Library" / "Application Support" / "JARVIS"))
)

# Quiet by design: this runs as a background listener, not a dev tool, so
# library log/progress noise (huggingface_hub download bars, openwakeword's
# "tried to import tflite runtime" notice, etc.) has nowhere useful to go.
# Must be set before those libraries are imported, which is why this lives
# at the top of config.py -- everything else imports config first.
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
logging.getLogger().setLevel(logging.ERROR)

PICOVOICE_ACCESS_KEY = os.environ.get("PICOVOICE_ACCESS_KEY")

# Sibling of this file (src/data/), not PROJECT_ROOT/data -- the flat src/
# layout keeps data/tests/scripts/packaging all under src/, not scattered
# at the repo root.
DATA_DIR = Path(__file__).resolve().parent / "data"
RESUME_PATH = DATA_DIR / "resume.json"
RESUME_SCHEMA_PATH = DATA_DIR / "resume.schema.json"
BACKUPS_DIR = DATA_DIR / "backups"
REVIEW_DIR = DATA_DIR / "review"

# Local LLM served by Ollama (https://ollama.com) -- no cloud API, no API key.
# `ollama pull` the model once via CLI before first use; see README.md.
# LLM_PROVIDER selects the LocalLLMProvider implementation (assistant/providers.py);
# only "ollama" exists today, kept configurable so a future MLXProvider slots in cleanly.
LLM_PROVIDER = os.environ.get("JARVIS_LLM_PROVIDER", "ollama")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
# qwen2.5:7b, not 14b -- measured live: once warm, the 7b model answered the
# same simple prompt in 1.1s vs 14b's 4.7s (roughly 4x), and still correctly
# drove a real tool call (résumé field update) in a separate live test.
# Ollama's default keep-alive is only 5 minutes, so without OLLAMA_KEEP_ALIVE
# below, "warm" rarely holds between JARVIS activations spaced by normal
# gaps -- the two fixes matter together, not either alone.
LOCAL_MODEL = os.environ.get("JARVIS_MODEL", "qwen2.5:7b")
# How long Ollama keeps the model resident in memory after the last request
# -- passed on every chat call (providers.py), not a server-side setting, so
# it works regardless of how the Ollama service itself was started. 30
# minutes comfortably covers normal gaps between JARVIS activations during a
# work session without holding the model in RAM indefinitely if left idle
# for a long stretch.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")

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

# Voice cloning (voice/xtts_engine.py), via XTTS-v2 -- an alternate
# TTS engine that clones a voice from a short user-supplied reference clip,
# instead of using one of macOS's built-in voices. Confirmed working live
# with a real reference clip, with good numbers (~13s to load the model,
# generation at real-time to faster-than-real-time) -- BUT its
# preload_in_background() call is currently NOT wired into run_voice_loop
# (see conversation.py's docstring): it made torchcodec dlopen the
# Homebrew-installed FFmpeg into the same process that already has
# faster-whisper's own bundled FFmpeg (via PyAV) loaded, and macOS logged a
# real ObjC class collision -- wake-word/clap detection stopped firing
# entirely, silently, right after. Fixed properly by moving XTTS synthesis
# into its own OS process (voice/xtts_worker.py, spawned by
# xtts_client.py) -- that FFmpeg/torchcodec loading now happens in a
# throwaway subprocess that never shares an address space with PvRecorder,
# so a repeat of that collision (if it ever recurs) stays contained there.
TTS_ENGINE = os.environ.get("TTS_ENGINE", "xtts")
TTS_XTTS_LANGUAGE = "pt"
# Deliberately NOT under DATA_DIR -- same reasoning as LOCAL_STATE_DIR
# above: this file is voice-identity data (arguably more sensitive than a
# session cookie), and this project sits inside a synced OneDrive folder.
# The reference clip itself is never fetched by JARVIS/Claude -- the user
# supplies it directly at this exact path.
TTS_XTTS_SPEAKER_WAV_PATH = LOCAL_STATE_DIR / "voice" / "jarvis_reference.wav"
# Fixed port (not dynamic like the visualizer's) -- the client needs to
# find the worker without any discovery mechanism, and only one worker
# ever runs per machine.
XTTS_WORKER_PORT = int(os.environ.get("XTTS_WORKER_PORT", "8766"))
WAKE_WORD = "jarvis"
STOP_PHRASES = ("tchau jarvis", "tchau, jarvis", "obrigado jarvis", "encerrar")

# "openwakeword" (default, no account/key -- ships a pretrained "hey jarvis"
# model) or "porcupine" (optional adapter, needs PICOVOICE_ACCESS_KEY).
WAKE_WORD_ENGINE = os.environ.get("WAKE_WORD_ENGINE", "openwakeword")

# A real, confirmed failure mode: PvRecorder's device_index=-1 means "the
# system's current default input device", which isn't a stable choice --
# a Bluetooth accessory (an Apple Watch) had silently become the default
# input, and a whole live session listened through its mic instead of the
# laptop's, with zero errors anywhere (the Watch's mic still "worked", it
# just wasn't pointed at the room). Substring-matched against
# PvRecorder.get_available_devices() at listener construction time
# (voice/wake_word.py); only falls back to the volatile system
# default if no device name contains this. "MacBook" specifically (not
# "Microphone"/"Microfone") because the model name isn't localized, unlike
# the rest of the device label.
PREFERRED_MIC_NAME_SUBSTRING = os.environ.get("PREFERRED_MIC_NAME_SUBSTRING", "MacBook")

# Two claps is a second, independent activation trigger that always runs
# alongside the wake-word engine above (see voice/engines/clap_detector.py).
# Peak amplitude, not RMS -- a clap's transient is a few ms long and RMS
# over an 80ms frame dilutes it too much to reliably cross a threshold.
# Amplitude-based detection is more environment-sensitive than the neural
# wake-word engines, so the threshold is a tunable env var, not fixed in code.
# Default lowered from 6000: a moderate clap at normal laptop-mic distance
# was empirically observed to often peak well below that. Run
# `python src/cli.py calibrate-claps` to see real peak values for your own
# mic/room and set this precisely instead of guessing.
CLAP_ACTIVATION_ENABLED = os.environ.get("CLAP_ACTIVATION_ENABLED", "true").lower() != "false"
CLAP_PEAK_THRESHOLD = float(os.environ.get("CLAP_PEAK_THRESHOLD", "3500"))
CLAP_WINDOW_SECONDS = float(os.environ.get("CLAP_WINDOW_SECONDS", "1.5"))

WHISPER_MODEL_SIZE = "small"
WHISPER_LANGUAGE = "pt"

SOURCE_RESUME_DOCS = [
    # 2026-09-07: real drift found live, in two stages. First: Nicholas
    # had renamed the on-disk files, dropping the " ATS" suffix this
    # constant expected -- fixed by pointing at the renamed files. But
    # those renamed files turned out to be the STYLED, two-column
    # résumé (a table with two empty top-level paragraphs -- confirmed
    # live: docx_extract.py's extract_text() only reads
    # document.paragraphs, so it silently returned almost nothing from
    # them), not the plain/linear "ATS" version docx_extract.py's own
    # docstring describes and expects. Rebuilt proper linear "... ATS"
    # .docx files (same real content, transcribed from the styled
    # pair's table cells, table-free) at Nicholas's explicit request
    # ("coloque os arquivos em ATS também") and pointed this back at
    # them -- these are the ones docx_extract.py can actually parse.
    "/Users/nicholasbirochi/Library/CloudStorage/OneDrive-FundaçãoSalvadorArena/Extras/Perfil/Currículos/Currículo - DataBase - Brasil ATS.docx",
    "/Users/nicholasbirochi/Library/CloudStorage/OneDrive-FundaçãoSalvadorArena/Extras/Perfil/Currículos/Currículo - DataBase - International ATS.docx",
]

# Incremental document indexer (indexing/) -- only these roots are ever
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

# Site adapters (sites/) -- Playwright-driven, one persistent browser
# session per site, saved under SITES_STATE_DIR (cookies -- never commit,
# and deliberately under LOCAL_STATE_DIR, NOT DATA_DIR -- see its comment
# above: this directory must never sync to OneDrive). Login is always a
# manual, one-time step in a real, visible browser window
# (sites/session.py) -- no password ever passes through this code.
# Domains verified against Gupy's own public pages (WebFetch), not guessed.
SITES_STATE_DIR = LOCAL_STATE_DIR / "sites"
GUPY_LOGIN_URL = "https://login.gupy.io/candidates/signin"
GUPY_PORTAL_URL = "https://portal.gupy.io/"
# The actual contact-info edit form (name/email/phone/CPF) -- found by
# navigating a real logged-in session: portal.gupy.io's "Meu currículo"
# link is a different page (experience/skills/diversity, no contact
# fields); contact info lives under "Editar perfil" instead.
GUPY_PROFILE_URL = "https://login.gupy.io/candidates/profile"
# Verified via WebFetch against vagas.com.br's own public homepage, not
# guessed. Profile edit URL is NOT filled in here -- unlike Gupy's, it's
# only reachable after a real login (no public equivalent to crawl), so
# it gets discovered live during vagas.py's first supervised session
# instead of being hardcoded ahead of time.
VAGAS_LOGIN_URL = "https://www.vagas.com.br/login-candidatos"
# Confirmed live: Vagas.com sits behind Cloudflare and resets the
# connection outright for Playwright's automated browser (net::
# ERR_CONNECTION_RESET), even headed and with the webdriver flag hidden --
# a stronger anti-automation signal than Gupy's. Per this project's own
# LinkedIn precedent (step back from sites that actively fight
# automation, don't escalate into stealth/evasion), vagas.py is paused at
# the login/session-check stage -- never wire inspect_current_profile/
# apply_changes for it without revisiting this.
#
# Confirmed via a real Catho signin/ redirects here, so this is the
# canonical URL, not the seguro.catho.com.br one. Unlike Vagas.com,
# Playwright DOES reach this one -- but only headed (confirmed live:
# headless=True gets a 403 "Forbidden" page, headless=False loads the
# real login page normally) -- see catho.py for where that's handled.
CATHO_LOGIN_URL = "https://www.catho.com.br/signin/"
# Found via WebSearch + confirmed reachable live. Best of the three so
# far: Playwright reaches it fine in BOTH headless and headed mode (no
# 403, no connection reset) -- infojobs.py can use config.SITES_HEADLESS
# normally, no per-site override needed like catho.py's.
INFOJOBS_LOGIN_URL = "https://login.infojobs.com.br/Account/Login"
# Found live on br.indeed.com's own homepage -- the "Acessar" link (not
# "Entrar"/"Login", which is why an earlier text-based search for those
# words missed it). Same pattern as Catho: Playwright reaches this fine
# headed but gets served a 403 "Blocked - Indeed.com" page headless
# (confirmed live) -- indeed.py hardcodes headless=False for that reason,
# same as catho.py.
INDEED_LOGIN_URL = "https://secure.indeed.com/auth?hl=pt_BR&co=BR&continue=https%3A%2F%2Fbr.indeed.com%2F"
# LinkedIn -- explicitly kept OUT of apply_changes/profile-editing per
# sites/base.py's own module docstring (real, well-documented
# account-restriction risk from aggressive anti-automation, and the user
# already handles LinkedIn profile updates manually themselves). Only
# read-only search_jobs() is in scope here, revisited 2026-08-11 at the
# user's explicit request, after confirming they understand the risk.
# Login is a real, isolated Playwright profile (same pattern as every
# other adapter here) -- NOT the user's real daily-driver browser, which
# Playwright has no way to read cookies/sessions from anyway.
LINKEDIN_LOGIN_URL = "https://www.linkedin.com/login"
# Headless by default so a normal `preview`/`apply` run doesn't pop a window;
# `login` always forces headed regardless, since it needs a human present.
SITES_HEADLESS = os.environ.get("SITES_HEADLESS", "true").lower() != "false"
# Audit-trail record written right after a real apply_changes() submission
# (which field changed, old/new value, when -- see gupy.py's _capture_evidence,
# deliberately NOT a full-page screenshot: the same profile page also shows
# CPF and birth date, and a screenshot would capture those incidentally even
# though the write itself never touches them). Same LOCAL_STATE_DIR tree as
# the session cookies, for the same reason.
SITES_EVIDENCE_DIR = SITES_STATE_DIR / "evidence"
