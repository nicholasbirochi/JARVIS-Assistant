"""Sensitive application-answer fields (RG and its issuing details, CPF,
parents' names, birthplace, level-based salary expectation, estado
civil) that Nicholas can choose to provide locally so JARVIS can fill
them into a real job-application form when a company's own screening
question asks for one of them.

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

2026-08-17: extended further, same explicit basis -- Nicholas sent a
real Gupy screening-question screenshot asking for the RG's issuing
authority/state, his mother's and father's names, and his birthplace
("naturalidade"), and asked for these to be fillable too. These are
classic Brazilian identity-verification fields (the same category
banks use as security questions), treated with the same care as RG/CPF
(see _HARD_PII_FIELDS in base.py) -- sensitive by nature, not casually
less so just because they weren't named in the project's original PII
rule.

Salary expectation is no longer a single flat value -- Nicholas asked
for three, one per level (estágio/júnior/pleno), because "pretensão
salarial" should honestly differ by which role is actually being
applied to. base.py's detect_level() classifies the listing; the
adapter picks the matching salary_<level> field at fill time.

2026-08-19: raca_cor/pcd added -- two more fixed, self-declared facts
("não sou PCD, sou branco"), used both to answer standard demographic
questions and (see job_matching.py's is_affirmative_action_only()) to
filter OUT listings explicitly reserved for people with disabilities or
a specific race, which Nicholas isn't eligible for. Also added
load_referral_contacts()/referral_contacts_path() -- a SEPARATE file
(referral_contacts.json, not this module's .env) holding real, named
people Nicholas already knows at specific companies who are willing to
refer him. Kept in its own file/format since it's naturally keyed data
(company -> {name, email}), not a fixed set of fields -- and because
it's a THIRD PARTY's real name and email, not Nicholas's own data, it
gets the exact same never-log/never-echo treatment as everything else
here, extended to protect someone else's PII too.

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
- Only the fields real Gupy questions have actually asked for (RG, RG
  issuing details, salary, mother's/father's names, naturalidade) or
  plausibly could ask for (CPF, estado civil -- not yet seen live,
  included preemptively since they're extremely common on Brazilian
  employment forms) are supported -- not an open-ended arbitrary-key
  store.

File format: plain KEY=value lines, "#" comments, blank lines ignored --
same shape as a normal .env file. No new dependency needed for
something this simple.
"""

from __future__ import annotations

from pathlib import Path

# field name -> the .env key it's read from. Field names here are the
# same ones base.py's classify_question_field() returns (except the
# three salary_* keys, which classify_question_field() never returns
# directly -- see gupy.py's level-aware resolution), so the two modules
# line up without a second translation table.
_FIELD_ENV_KEYS: dict[str, str] = {
    "rg": "JARVIS_APPLICATION_RG",
    "rg_orgao_estado": "JARVIS_APPLICATION_RG_ORGAO_ESTADO",
    "cpf": "JARVIS_APPLICATION_CPF",
    "nome_mae": "JARVIS_APPLICATION_NOME_MAE",
    "nome_pai": "JARVIS_APPLICATION_NOME_PAI",
    "naturalidade": "JARVIS_APPLICATION_NATURALIDADE",
    "raca_cor": "JARVIS_APPLICATION_RACA_COR",
    "pcd": "JARVIS_APPLICATION_PCD",
    "salary_estagio": "JARVIS_APPLICATION_SALARY_ESTAGIO",
    "salary_junior": "JARVIS_APPLICATION_SALARY_JUNIOR",
    "salary_pleno": "JARVIS_APPLICATION_SALARY_PLENO",
    "marital_status": "JARVIS_APPLICATION_MARITAL_STATUS",
    # 2026-08-21: the recurring, generic company questions -- see
    # base.py's _FIELD_TERMS comment. "linkedin" and "ja_trabalhou_aqui"
    # deliberately have NO entry here -- they're resolved elsewhere
    # (the résumé's own public link, and a fixed "Não" respectively),
    # not from this confidential-data file.
    "cnh": "JARVIS_APPLICATION_CNH",
    "disponibilidade_viagem": "JARVIS_APPLICATION_DISPONIBILIDADE_VIAGEM",
    "disponibilidade_fds": "JARVIS_APPLICATION_DISPONIBILIDADE_FDS",
    "escolaridade": "JARVIS_APPLICATION_ESCOLARIDADE",
    # 2026-08-21, round 2 -- found live during the one-at-a-time apply
    # batch. "disponibilidade_inicio_imediato" deliberately has NO entry
    # here -- resolved from the résumé's own job_preferences.availability
    # instead (same reasoning as "linkedin").
    "cargo_atual": "JARVIS_APPLICATION_CARGO_ATUAL",
    "parentes_na_empresa": "JARVIS_APPLICATION_PARENTES_NA_EMPRESA",
    "semestre_formatura": "JARVIS_APPLICATION_SEMESTRE_FORMATURA",
}


def profile_path() -> Path:
    from jarvis.config import LOCAL_STATE_DIR

    return LOCAL_STATE_DIR / "application_profile.env"


def load_application_profile() -> dict[str, str | None]:
    """Reads profile_path() and returns every known field (see
    _FIELD_ENV_KEYS). A missing file, or missing individual keys, just
    come back None -- not having this set up yet is a normal state,
    never an error. Never logs or prints the raw file contents."""
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
            *(f"{env_key}=" for env_key in _FIELD_ENV_KEYS.values()),
            "",
        ]
    )
    path.write_text(template, encoding="utf-8")
    return path


def referral_contacts_path() -> Path:
    from jarvis.config import LOCAL_STATE_DIR

    return LOCAL_STATE_DIR / "referral_contacts.json"


def load_referral_contacts() -> dict[str, dict[str, str]]:
    """Reads referral_contacts_path() -- real, named people Nicholas
    already knows at specific companies who are willing to refer him
    (2026-08-19: three real contacts at Itaú/Santander/XP). Keyed by a
    short company identifier (matched against a listing's company name
    by base.py's find_referral_contact()), each value a {"name":
    ..., "email": ...} dict. JSON here (not the flat .env format) since
    this is naturally nested, keyed data, not a fixed set of fields.
    Missing file returns {} -- not having this set up is a normal
    state, never an error. Never logs or prints the raw contents (these
    are a THIRD PARTY's real name and email, not even Nicholas's own
    data -- the same never-log/never-echo discipline applies)."""
    path = referral_contacts_path()
    if not path.exists():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}
