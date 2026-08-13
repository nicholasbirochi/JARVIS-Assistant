"""Sensitive application-answer fields (RG, CPF, salary expectation,
estado civil) that Nicholas can choose to provide locally so JARVIS can
fill them into a real job-application form when a company's own
screening question asks for one of them.

Deliberately different from base.py's "never fabricate/guess" rule:
fabrication means JARVIS inventing an answer with no real source. This
is real, Nicholas-provided data flowing through a channel he controls
(a local file he edits himself), used for the specific, narrow purpose
of completing an application he already started -- not JARVIS guessing
or scraping this from anywhere.

2026-08-13: explicitly confirmed with Nicholas, after being told this
reverses this project's original "never capture RG/CPF, even
incidentally" rule, that he wants RG and CPF included here too, not
just salary/estado civil.

Real design constraints, all load-bearing for keeping this safe:
- Lives at LOCAL_STATE_DIR/application_profile.env -- same location as
  site session cookies (jarvis/sites/session.py), OUTSIDE the
  OneDrive-synced project folder and outside git, for the same reason:
  this is live personal data, never something that belongs in git
  history or a synced folder.
- Read fresh on every use, directly by adapter code, straight into a
  Playwright .fill() call. NEVER passed as an LLM tool-call argument
  (that would put it in conversation context/any transcript logging)
  and the actual values must NEVER be included in evidence JSON files,
  ApplicationQuestion.answer, or any log/print output -- callers must
  only ever say WHICH field was filled (e.g. "RG: preenchido do
  arquivo local"), never the value itself. See gupy.py's
  _record_evidence, which already avoids screenshotting CPF/birth date
  for the same reason on the profile-edit side; this extends that same
  discipline to a new source.
- Only the four fields real Gupy questions have actually asked for (RG,
  salary) or plausibly could ask for (CPF, estado civil -- not yet seen
  live, included preemptively since they're extremely common on
  Brazilian employment forms) are supported -- not an open-ended
  arbitrary-key store.

File format: plain KEY=value lines, "#" comments, blank lines ignored --
same shape as a normal .env file. No new dependency needed for
something this simple.
"""

from __future__ import annotations

from pathlib import Path

# field name -> the .env key it's read from. Field names here are the
# same ones base.py's classify_question_field() returns, so the two
# modules line up without a second translation table.
_FIELD_ENV_KEYS: dict[str, str] = {
    "rg": "JARVIS_APPLICATION_RG",
    "cpf": "JARVIS_APPLICATION_CPF",
    "salary_expectation": "JARVIS_APPLICATION_SALARY_EXPECTATION",
    "marital_status": "JARVIS_APPLICATION_MARITAL_STATUS",
}


def profile_path() -> Path:
    from jarvis.config import LOCAL_STATE_DIR

    return LOCAL_STATE_DIR / "application_profile.env"


def load_application_profile() -> dict[str, str | None]:
    """Reads profile_path() and returns the four known fields (rg, cpf,
    salary_expectation, marital_status). A missing file, or missing
    individual keys, just come back None -- not having this set up yet
    is a normal state, never an error. Never logs or prints the raw
    file contents."""
    path = profile_path()
    raw: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            raw[key.strip()] = value.strip()
    return {field: (raw.get(env_key) or None) for field, env_key in _FIELD_ENV_KEYS.items()}


def ensure_profile_template() -> Path:
    """Writes an empty, commented template to profile_path() if nothing
    exists there yet -- so Nicholas has a real file to fill in with a
    text editor instead of having to construct the exact KEY=value
    format from a docstring. Never overwrites an existing file (never
    silently discards values he already entered)."""
    path = profile_path()
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    template = "\n".join(
        [
            "# Preenchido por você, lido só localmente pelo JARVIS -- nunca sincronizado,",
            "# nunca commitado, nunca logado. Usado só para preencher perguntas de",
            "# candidatura que pedem esses dados especificamente.",
            "JARVIS_APPLICATION_RG=",
            "JARVIS_APPLICATION_CPF=",
            "JARVIS_APPLICATION_SALARY_EXPECTATION=",
            "JARVIS_APPLICATION_MARITAL_STATUS=",
            "",
        ]
    )
    path.write_text(template, encoding="utf-8")
    return path
