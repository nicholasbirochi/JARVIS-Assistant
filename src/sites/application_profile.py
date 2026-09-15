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
  site session cookies (sites/session.py), OUTSIDE the
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
    # 2026-09-07: distinct from the three above -- a question about
    # CURRENT/PAST salary ("último salário") is a different fact than
    # desired salary, see base.py's _FIELD_TERMS comment for the real
    # classification bug this fixes.
    "salary_current": "JARVIS_APPLICATION_SALARY_CURRENT",
    "marital_status": "JARVIS_APPLICATION_MARITAL_STATUS",
    # 2026-08-21: the recurring, generic company questions -- see
    # base.py's _FIELD_TERMS comment. "linkedin" and "ja_trabalhou_aqui"
    # deliberately have NO entry here -- they're resolved elsewhere
    # (the résumé's own public link, and a fixed "Não" respectively),
    # not from this confidential-data file.
    "cnh": "JARVIS_APPLICATION_CNH",
    # 2026-09-07, found live (TELEMONT): a radio-only "categoria" follow-
    # up needs just the bare letter (e.g. "B"), unlike "cnh" above (a
    # free-text field holding the full "Sim, categoria B" sentence) --
    # see base.py's _FIELD_TERMS comment.
    "cnh_categoria": "JARVIS_APPLICATION_CNH_CATEGORIA",
    "disponibilidade_viagem": "JARVIS_APPLICATION_DISPONIBILIDADE_VIAGEM",
    "disponibilidade_fds": "JARVIS_APPLICATION_DISPONIBILIDADE_FDS",
    # 2026-08-27, round 3 -- found live (Núclea/Stefanini): hybrid/
    # in-person work arrangement, distinct from disponibilidade_viagem
    # (travel) and disponibilidade_fds (weekends).
    "disponibilidade_hibrido": "JARVIS_APPLICATION_DISPONIBILIDADE_HIBRIDO",
    "escolaridade": "JARVIS_APPLICATION_ESCOLARIDADE",
    # 2026-08-21, round 2 -- found live during the one-at-a-time apply
    # batch. "disponibilidade_inicio_imediato" deliberately has NO entry
    # here -- resolved from the résumé's own job_preferences.availability
    # instead (same reasoning as "linkedin").
    "cargo_atual": "JARVIS_APPLICATION_CARGO_ATUAL",
    "parentes_na_empresa": "JARVIS_APPLICATION_PARENTES_NA_EMPRESA",
    "semestre_formatura": "JARVIS_APPLICATION_SEMESTRE_FORMATURA",
    # 2026-09-07, found live across 4 TELEMONT postings in the same
    # batch-apply run -- a recurring physical-uniform question pair.
    # "tamanho_uniforme" holds a bare size letter (PP/P/M/G/GG) -- a
    # real, live DOM check found this is a radio group, not free text
    # (corrected from an earlier, wrong "shoe size" guess).
    "altura": "JARVIS_APPLICATION_ALTURA",
    "tamanho_uniforme": "JARVIS_APPLICATION_TAMANHO_UNIFORME",
    # 2026-09-14: self-rated tool proficiency -- genuinely new facts, not
    # derivable from the résumé's skills list (which names tools but not
    # a self-assessed level), unlike "telefone"/"curso_nome"/
    # "ingles_nivel"/"portfolio_link"/"graduacao_completa" (see base.py's
    # apply_resume_backed_profile_fields(), which pulls those straight
    # from data/resume.json instead -- no .env entry needed for them).
    "excel_nivel": "JARVIS_APPLICATION_EXCEL_NIVEL",
    "sql_nivel": "JARVIS_APPLICATION_SQL_NIVEL",
    "powerbi_nivel": "JARVIS_APPLICATION_POWERBI_NIVEL",
    # 2026-09-14: real, honest answers (including real negatives) drafted
    # by a separate assistant Nicholas consulted (web access to his
    # public LinkedIn, cross-checked against his résumé) for a batch of
    # real, live-blocked InfoJobs screening questions -- see base.py's
    # _FIELD_TERMS comment for the full list and reasoning. Narrow,
    # single-purpose fields on purpose, not a generic answer bank.
    "disponibilidade_estagio_09_16": "JARVIS_APPLICATION_DISPONIBILIDADE_ESTAGIO_09_16",
    "estatistica_matematica_financeira": "JARVIS_APPLICATION_ESTATISTICA_MATEMATICA_FINANCEIRA",
    "call_center_experiencia": "JARVIS_APPLICATION_CALL_CENTER_EXPERIENCIA",
    "power_query_dax": "JARVIS_APPLICATION_POWER_QUERY_DAX",
    "power_automate_nivel": "JARVIS_APPLICATION_POWER_AUTOMATE_NIVEL",
    "google_sheets_nivel": "JARVIS_APPLICATION_GOOGLE_SHEETS_NIVEL",
    "ia_experiencia": "JARVIS_APPLICATION_IA_EXPERIENCIA",
    "susep_conhecimento": "JARVIS_APPLICATION_SUSEP_CONHECIMENTO",
    "txt_csv_conhecimento": "JARVIS_APPLICATION_TXT_CSV_CONHECIMENTO",
    "kpis_comerciais_experiencia": "JARVIS_APPLICATION_KPIS_COMERCIAIS_EXPERIENCIA",
    "indicadores_experiencia": "JARVIS_APPLICATION_INDICADORES_EXPERIENCIA",
    "disponibilidade_temporario": "JARVIS_APPLICATION_DISPONIBILIDADE_TEMPORARIO",
    "ferramentas_analise_dominadas": "JARVIS_APPLICATION_FERRAMENTAS_ANALISE_DOMINADAS",
    "ferramentas_visualizacao_dominadas": "JARVIS_APPLICATION_FERRAMENTAS_VISUALIZACAO_DOMINADAS",
    "como_constroi_dashboards": "JARVIS_APPLICATION_COMO_CONSTROI_DASHBOARDS",
    "resultado_real_dados": "JARVIS_APPLICATION_RESULTADO_REAL_DADOS",
    "diferencial_analista": "JARVIS_APPLICATION_DIFERENCIAL_ANALISTA",
    "atividades_vaga_experiencia": "JARVIS_APPLICATION_ATIVIDADES_VAGA_EXPERIENCIA",
    "etl_ferramentas_experiencia": "JARVIS_APPLICATION_ETL_FERRAMENTAS_EXPERIENCIA",
    "python_dbt_conhecimento": "JARVIS_APPLICATION_PYTHON_DBT_CONHECIMENTO",
    "contas_pagar_receber": "JARVIS_APPLICATION_CONTAS_PAGAR_RECEBER",
    "dre_relatorios_financeiros": "JARVIS_APPLICATION_DRE_RELATORIOS_FINANCEIROS",
    "tecnologia_area_financeira": "JARVIS_APPLICATION_TECNOLOGIA_AREA_FINANCEIRA",
    "analise_dados_financeiros": "JARVIS_APPLICATION_ANALISE_DADOS_FINANCEIROS",
    "mmm_experiencia": "JARVIS_APPLICATION_MMM_EXPERIENCIA",
    "inteligencia_mercado_experiencia": "JARVIS_APPLICATION_INTELIGENCIA_MERCADO_EXPERIENCIA",
    "market_share_indicadores": "JARVIS_APPLICATION_MARKET_SHARE_INDICADORES",
    "relatorios_executivos_experiencia": "JARVIS_APPLICATION_RELATORIOS_EXECUTIVOS_EXPERIENCIA",
    "crm_experiencia": "JARVIS_APPLICATION_CRM_EXPERIENCIA",
    "looker_apps_script": "JARVIS_APPLICATION_LOOKER_APPS_SCRIPT",
    "python_dados_nivel": "JARVIS_APPLICATION_PYTHON_DADOS_NIVEL",
    "melhoria_continua_exemplo": "JARVIS_APPLICATION_MELHORIA_CONTINUA_EXEMPLO",
    "graduacao_area_tecnica": "JARVIS_APPLICATION_GRADUACAO_AREA_TECNICA",
    "mestrado_concluido": "JARVIS_APPLICATION_MESTRADO_CONCLUIDO",
    "conte_sua_experiencia": "JARVIS_APPLICATION_CONTE_SUA_EXPERIENCIA",
}


def profile_path() -> Path:
    from config import LOCAL_STATE_DIR

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
    from config import LOCAL_STATE_DIR

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
