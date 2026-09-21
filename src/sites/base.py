"""Common interface every job-site adapter will implement (Phase 5+ -- not
implemented yet, this is the interface + supporting types only).

Design decisions, settled now so every future adapter follows the same
contract:

- Login is always a one-time MANUAL step in a real browser window. Playwright
  persists the authenticated session afterwards via `storage_state`/a
  per-site user-data-dir. No password ever passes through this app's code --
  "never store site passwords in plaintext" is satisfied by construction
  (there's no password to store), not by encrypting one.
- `apply_changes` is the ONLY method allowed to mutate anything on the real
  site, and it refuses unless called with `confirmed=True` -- set only after
  a human has seen `preview_changes()`'s output. Dry-run first, always.
- If a site demands MFA/CAPTCHA/any additional verification, the adapter
  must surface that as a SessionStatus (not attempt to solve or bypass it)
  and hand control back to the user.
- Never claim full support for a site until its real flows have actually
  been tested end-to-end against that site.

Recommendation for the first real adapter: Gupy, not LinkedIn.
LinkedIn has aggressive, well-documented anti-automation infrastructure
(behavioral/device fingerprinting, rate limiting, CAPTCHA, and explicit ToS
language against automating profile edits) -- real account-restriction risk
that's disproportionate to automating a few infrequent field edits on one
personal account. Gupy is a Brazilian candidate-facing ATS built around an
editable candidate profile as a first-class, expected user action -- closer
to routine form CRUD than an adversarial target. This is a reasoned relative
judgment, not a verified fact -- validate empirically with a slow, low-volume,
human-paced session against the real account before investing real
engineering time. If LinkedIn is ever revisited, restrict it to
`check_session`/`preview_changes` only -- never wire `apply_changes` for it.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from resume.schema import Resume


class SessionStatus(str, Enum):
    AUTHENTICATED = "authenticated"
    NOT_LOGGED_IN = "not_logged_in"
    REQUIRES_MFA = "requires_mfa"
    REQUIRES_CAPTCHA = "requires_captcha"
    SESSION_EXPIRED = "session_expired"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class SiteProfileSnapshot:
    """Read-only scrape of what the site currently shows -- the "before"
    side of the diff that build_update_plan() compares against."""

    site_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    captured_at: str = ""


@dataclass
class PlannedFieldChange:
    site_field: str
    current_value: Any
    new_value: Any
    resume_field_path: str


@dataclass
class UpdatePlan:
    site_name: str
    changes: list[PlannedFieldChange] = field(default_factory=list)


@dataclass
class ChangePreview:
    """Rendered diff for human review -- produced by preview_changes(),
    never submits anything. This is the "dry run" the user must see before
    apply_changes() can be called with confirmed=True."""

    site_name: str
    plan: UpdatePlan
    summary_text: str


@dataclass
class UpdateResult:
    site_name: str
    applied: bool
    changes_applied: list[PlannedFieldChange] = field(default_factory=list)
    error: str | None = None
    evidence_path: str | None = None  # screenshot/log captured for the audit trail


@dataclass
class JobListing:
    """One search result from a site's own job search -- read-only, no
    relation to the candidate-profile types above. site_name + external_id
    together are the natural dedupe key across repeated searches; url is
    always absolute (adapters must resolve any site-relative href before
    constructing this)."""

    site_name: str
    external_id: str
    title: str
    company: str | None
    location: str | None
    url: str
    snippet: str | None = None
    salary: str | None = None


# --- Job-application flow (as opposed to profile editing above) -----------
#
# Added 2026-08-12 after a real, live, human-supervised pilot against a
# genuine Gupy listing (Itaú Unibanco, "Tech Lead | Engenharia de
# Software"): the very first real employer screening step encountered
# asked for the candidate's RG (Brazilian government ID number) and
# current salary ("Qual a sua remuneração atual?"), with an explicit
# on-page warning that answers "não poderão ser editadas depois". This is
# exactly the same class of data this project has refused to capture/store
# since its very first design decision (CPF/birth date) -- so the same
# rule now extends to job-application screening questions: JARVIS must
# NEVER fabricate or guess an answer to a company's own custom question,
# full stop, no exceptions, regardless of how "obvious" an answer might
# seem. question_requires_stop() below is a real, confirmed-live signal
# list, not a hypothetical.
#
# A second, broader rule sits on top of that one: this project does not
# yet auto-answer ANY company-specific question, even ones that look
# perfectly safe (a plain yes/no about tool experience, say) -- because
# "safe-looking" is a guess, and getting one wrong submits an dishonest
# answer to a real employer that (per the same live finding) can't be
# edited afterward. Only Gupy's own two STANDARD platform questions
# (referral / "do you work here") are auto-answered, because their
# meaning is fixed platform-wide and both are unambiguously "Não" for any
# external candidate applying cold -- never a per-company guess.
# Maps each field JARVIS can fill from a Nicholas-provided local profile
# (see sites/application_profile.py) to the terms that identify a
# screening question as asking for it. "data de nascimento" (birth date)
# is deliberately NOT one of these -- even after Nicholas confirmed
# RG/CPF should be fillable (2026-08-13), birth date has no fill path at
# all and stays an unconditional stop (see _UNFILLABLE_HARD_STOP_TERMS
# below) -- narrower in scope than what was first offered to him, kept
# out because there's no real, recurring need for it seen live yet.
#
# Dict ORDER matters: classify_question_field() returns on the first
# match while iterating this dict, so "rg_orgao_estado" must be checked
# before the bare "rg" -- a real question text like "Órgão e Estado de
# emissão do RG" contains "RG" as its own whole word too, so checking
# "rg" first would misclassify it (and try to fill the RG NUMBER
# selector with an issuing-authority value).
#
# nome_mae/nome_pai/naturalidade added 2026-08-17, same explicit consent
# as RG/CPF -- classic Brazilian identity-verification fields (a bank's
# own "security question" data), not casually less sensitive just
# because they weren't named in the project's original PII rule.
#
# raca_cor/pcd added 2026-08-19: Nicholas stated two fixed, durable
# facts about himself ("não sou PCD, sou branco") -- these are real,
# self-declared demographic answers, not guesses, and they double as the
# basis for filtering out affirmative-action-exclusive listings he
# isn't eligible for (see job_matching.py's is_affirmative_action_only()).
_FIELD_TERMS: dict[str, list[str]] = {
    "rg_orgao_estado": ["órgão e estado de emissão", "orgao e estado de emissao", "órgão emissor", "orgao emissor"],
    "rg": ["rg", "registro geral", "carteira de identidade"],
    "cpf": ["cpf"],
    # 2026-09-07, real gap found live in the Gupy batch-apply run: "nome
    # DA SUA mãe"/"nome DO SEU pai" (Grupo Nós and others) don't contain
    # "nome da mãe"/"nome do pai" as substrings at all -- the inserted
    # "sua"/"seu" broke the match, same class of miss as every other
    # "different real phrasing" fix in this dict.
    "nome_mae": ["nome da mãe", "nome da mae", "nome da sua mãe", "nome da sua mae"],
    "nome_pai": ["nome do pai", "nome do seu pai"],
    # "cidade e estado de nascimento" (2026-09-07, same batch): a very
    # common real phrasing for the exact same question that never says
    # the word "naturalidade" at all.
    "naturalidade": ["naturalidade", "cidade e estado de nascimento", "cidade de nascimento"],
    "raca_cor": ["raça", "raca", "cor da pele", "etnia"],
    # 2026-08-27, real false-positive found live (Stefanini): the bare
    # "pcd" abbreviation matched a COMPLETELY different question ("Você
    # chegou até esta oportunidade por meio de alguma instituição...
    # (PcD ou não PcD)?" -- a referral-institution radio group, not a
    # disability-status question) purely because it mentions "PcD"
    # parenthetically. A genuine PCD question always spells out "pessoa
    # com deficiência" too (confirmed across every real listing seen so
    # far), so the bare abbreviation added false-positive risk without
    # ever being needed to catch a real one -- removed.
    "pcd": ["pessoa com deficiência", "pessoa com deficiencia"],
    # 2026-09-07, real classification bug found live on InfoJobs (Monitor
    # De Qualidade Jr E Pl and others): "Qual foi seu último salário?" /
    # "Qual sua última remuneração?" ask for a CURRENT/PAST fact, not the
    # desired figure -- but the bare "remuneração"/"salário" terms below
    # were classifying it as "salary_expectation" and answering with the
    # DESIRED salary (salary_junior etc.), a real, factually wrong answer
    # sent to a real employer. This is exactly the gap the module's own
    # 2026-08-12 design note (a real Itaú listing asking "remuneração
    # ATUAL") already flagged as a risk -- it just hadn't been hit by a
    # question phrased this plainly until now. Checked BEFORE
    # "salary_expectation" (dict order) since these phrases also contain
    # the bare substrings "remuneração"/"salário".
    "salary_current": [
        "último salário",
        "ultimo salario",
        "última remuneração",
        "ultima remuneracao",
        "remuneração atual",
        "remuneracao atual",
        "salário atual",
        "salario atual",
        "remuneração anterior",
        "remuneracao anterior",
    ],
    "salary_expectation": [
        "remuneração",
        "remuneracao",
        "salário",
        "salario",
        "pretensão salarial",
        "pretensao salarial",
        "renda",
        # 2026-09-07, real gap found live in the Gupy batch-apply run:
        # "expectativa salarial" is the same question, worded
        # differently -- doesn't contain "salário"/"pretensão" at all.
        "expectativa salarial",
    ],
    "marital_status": ["estado civil"],
    # 2026-08-21: compiled from the actual, real company-question text
    # seen live across several listings (Autoglass, ALS Life Sciences,
    # Camed Corretora, Fundação Itaú and others) -- the most generic,
    # recurring ones, not a guess ("me mande as perguntas mais
    # genéricas e que sempre aparecem"). "linkedin" is resolved from the
    # résumé's own public links (not the confidential .env profile --
    # see application_profile.py). "ja_trabalhou_aqui" gets a fixed
    # "Não" answer in gupy.py rather than a real .env value -- same
    # reasoning as the standard referral question's own "você trabalha
    # na empresa?" (always false for an external candidate), not
    # something that needs asking every time.
    "linkedin": ["linkedin"],
    # 2026-09-07, found live (TELEMONT): "Possui CNH? Se SIM, informe a
    # categoria." is a SEPARATE radio group with bare-letter options
    # (A/B/C/D/E), unlike the ordinary free-text "cnh" question
    # elsewhere -- the full "cnh" profile value ("Sim, categoria B")
    # doesn't match a bare "B" option, so this needs its own field
    # holding just the letter. Checked BEFORE "cnh" (dict iteration
    # order matters here) since this phrasing also contains the bare
    # substring "cnh" and would otherwise match that first.
    "cnh_categoria": ["se sim, informe a categoria"],
    "cnh": ["cnh", "carteira nacional de habilitação", "carteira nacional de habilitacao"],
    "ja_trabalhou_aqui": [
        "ex-colaborador",
        "ex colaborador",
        "já trabalhou nesta empresa",
        "ja trabalhou nesta empresa",
        "já trabalhou nessa empresa",
        "ja trabalhou nessa empresa",
        # 2026-08-21, real miss found live (Cogna): "do grupo" phrasing
        # is the same question, worded differently.
        "trabalhou em alguma empresa do grupo",
        # 2026-09-07, real miss found live in the Gupy batch-apply run:
        # "atuou" instead of "trabalhou" -- same question. NOTE: a
        # genuinely common real phrasing, "já trabalhou na <nome da
        # empresa>?", is NOT covered here on purpose -- a bare regex for
        # "trabalhou n[ao] <anything>" would also match a real, DIFFERENT
        # question ("já trabalhou no exterior?", asking about
        # international experience in general, not at this specific
        # company) with the wrong fixed "Não" answer. Safely
        # generalizing that one needs the current listing's own company
        # name as context, which classify_question_field() doesn't have
        # -- a real, known gap, not fixed here.
        "atuou em alguma empresa do grupo",
    ],
    "disponibilidade_viagem": ["disponibilidade para viajar", "disponível para viajar", "disponivel para viajar"],
    "disponibilidade_fds": [
        "trabalhar aos sábados",
        "trabalhar aos sabados",
        "disponibilidade para fins de semana",
        "disponibilidade para final de semana",
    ],
    # 2026-08-27, real gap found live in the same one-at-a-time apply
    # batch (Núclea: "modelo híbrido (presencial 2x por semana)";
    # Stefanini: "modelo hibrido, sendo 3 x semana") -- same underlying
    # question (hybrid/in-person work arrangement), two real phrasings,
    # neither mentioning "viajar" or "fins de semana" so this needed its
    # own field rather than reusing disponibilidade_viagem/_fds.
    "disponibilidade_hibrido": ["modelo híbrido", "modelo hibrido"],
    "escolaridade": [
        "ensino superior completo",
        "superior completo",
        "escolaridade",
        # 2026-08-21, real miss found live (Stefanini): same question,
        # different phrasing.
        "graduação completa ou em andamento",
        "graduacao completa ou em andamento",
    ],
    # 2026-08-21, round 2 of the recurring-questions expansion -- found
    # live during the one-at-a-time apply batch (FGC/PagSeguro/
    # Stefanini). "disponibilidade_inicio_imediato" is resolved from the
    # résumé's own job_preferences.availability.status (already
    # "immediate" there), same reasoning as "linkedin" -- no need for a
    # separate .env value duplicating a fact already on record.
    # "cargo_atual"/"parentes_na_empresa"/"semestre_formatura" need real
    # .env values from Nicholas.
    "disponibilidade_inicio_imediato": [
        "disponibilidade para início imediato",
        "disponibilidade para inicio imediato",
        "início imediato",
        "inicio imediato",
    ],
    # 2026-09-14, real miss found live (InfoJobs, "Analista de Dados --
    # 11885861" and others): "Está trabalhando no momento?"/"Está
    # trabalhando atualmente?" ask the exact same underlying fact as
    # "cargo atual" (a boolean-shaped phrasing of it), and the existing
    # descriptive value ("Estagiário em Análise de Dados na Volkswagen
    # do Brasil...") is itself an informative, honest answer to either
    # phrasing -- reused rather than duplicated into a separate field.
    "cargo_atual": [
        "qual é o seu cargo atual",
        "qual e o seu cargo atual",
        "cargo atual",
        "está trabalhando no momento",
        "esta trabalhando no momento",
        "está trabalhando atualmente",
        "esta trabalhando atualmente",
    ],
    "parentes_na_empresa": [
        "possui parentes que trabalham",
        "tem parentesco com algum colaborador",
        "possui parentesco com algum colaborador",
        # 2026-08-21, real miss found live (Vivo): "você tem parente(s)"
        # is the same nepotism-disclosure question, worded differently.
        "você tem parente",
        "voce tem parente",
        # 2026-09-07, real miss found live in the Gupy batch-apply run:
        # "familiar ou parente que atualmente trabalha" -- same
        # nepotism-disclosure question, yet another phrasing.
        "familiar ou parente que atualmente trabalha",
        # 2026-09-14, real miss found live (InfoJobs, Ânima Educação):
        # a parenthetical list of relationship degrees inserted between
        # "parentesco" and "com algum colaborador" breaks the two
        # existing contiguous-phrase terms above -- this fragment alone
        # survives that insertion.
        "com algum colaborador atual da",
    ],
    # 2026-08-22, real gap found live (PagBank): a conditional follow-up
    # to "parentes_na_empresa" above, asking for the actual name/degree
    # of kinship -- some companies' forms render this unconditionally,
    # even when the parent answer is "Não" and there's genuinely no one
    # to name. See gupy.py's _CONDITIONAL_SKIP_FIELDS for how this gets
    # skipped rather than blocking the whole application when that's the
    # case -- deliberately has NO entry in application_profile.py's
    # _FIELD_ENV_KEYS, since Nicholas never needs a real value here (his
    # own parentes_na_empresa is always "Não").
    "parentes_nome_grau": ["nome e grau de parentesco", "grau de parentesco"],
    # 2026-09-07, real recurring question found live across 4 TELEMONT
    # postings in the same batch-apply run: a physical-uniform question
    # pair, always phrased the same way ("Em caso de utilização de
    # uniforme, informe sua altura/numeração"). Genuinely reusable --
    # same two questions, same real answers, on every posting that asks.
    "altura": ["informe sua altura"],
    # 2026-09-07, corrected after a real, live submission attempt:
    # TELEMONT's "numeração" is NOT shoe size (my first, wrong guess) --
    # it's a radio group of uniform LETTER sizes (PP/P/M/G/GG), confirmed
    # live by dumping the real DOM. Renamed from "numeracao_calcado" to
    # reflect that; the exact-match radio-selection path
    # (_select_radio_or_checkbox_answer()) needs the bare letter value
    # ("G"), not a shoe-size number.
    "tamanho_uniforme": ["informe qual a numeração", "numeração do uniforme", "numeracao do uniforme"],
    # 2026-08-21, real miss found live (Vivo): "nome completo, sem
    # abreviações" -- resolved from the résumé's own personal_info.
    # full_name, not a separate .env value (same reasoning as
    # "linkedin" -- it's not confidential, it's already on the résumé).
    # 2026-09-14: also added the bare "nome completo" (found live,
    # InfoJobs, a Killer Questions field asking only that with no
    # qualifier at all) -- deliberately NOT extended to a generic
    # "\bnome\b" term, which would risk answering a genuinely different
    # question (e.g. a reference's or supervisor's name) with Nicholas's
    # own; "nome completo" specifically, in a candidate screening form,
    # has been consistently about the applicant in every real case seen.
    "nome_completo": [
        "nome completo, sem abreviações",
        "nome completo sem abreviações",
        "nome completo, sem abreviacoes",
        "nome completo",
    ],
    "semestre_formatura": [
        "semestre e o ano previstos para a conclusão do curso",
        "semestre e o ano previstos para a conclusao do curso",
        "previsão de formatura",
        "previsao de formatura",
        # 2026-09-14, real miss found live (InfoJobs, "Estágio Estatística
        # -- Planning/Pricing"): same question (current semester + expected
        # graduation date), worded without "previsão de formatura" at all.
        "semestre atual e a previsão de conclusão",
        "semestre atual e a previsao de conclusao",
    ],
    # 2026-09-14, compiled from a batch of real, live-blocked InfoJobs
    # listings after Nicholas had a separate Claude instance (with access
    # to his OneDrive résumé) look them up -- every one of these is
    # already public/on-record data (résumé, not the confidential .env
    # profile), resolved from data/resume.json by
    # apply_resume_backed_profile_fields() below, same reasoning as
    # "linkedin"/"nome_completo" above.
    "telefone": ["número de whatsapp", "numero de whatsapp", "whatsapp"],
    "curso_nome": [
        "nome do seu curso superior atual",
        "nome do seu curso",
        "nome do curso superior atual",
        # 2026-09-14, real misses found live (InfoJobs, several
        # listings): "qual a sua formação acadêmica" and "titulação
        # (nome do curso, ...)" ask for the same résumé-composed fact
        # (course + institution + status) worded two more ways, neither
        # containing "seu curso" at all.
        "sua formação acadêmica",
        "sua formacao academica",
        "nome do curso",
        "titulação",
        "titulacao",
    ],
    "ingles_nivel": [
        "nível de conhecimento em inglês",
        "nivel de conhecimento em ingles",
        "seu nível de inglês",
        "seu nivel de ingles",
        "nível de inglês",
        "nivel de ingles",
        "conhecimento em inglês",
        "conhecimento em ingles",
        "inglês em nível",
        "ingles em nivel",
        # 2026-09-14, real miss found live (InfoJobs, "Analista de Dados
        # -- Dashboards"): a bare "Inglês avançado?" with no "nível de"
        # framing at all.
        "inglês avançado",
        "ingles avancado",
        # 2026-09-21, real miss found live (Gupy batch-apply run, MTP
        # Métodos e Tecnologia): "proficiência em inglês" is the same
        # question, worded with "proficiência" instead of "nível"/
        # "conhecimento" -- neither existing term covers it.
        "proficiência em inglês",
        "proficiencia em ingles",
    ],
    "portfolio_link": ["link do seu portfólio", "link do seu portfolio", "portfólio ou projetos de referência"],
    # Self-rated tool proficiency -- genuinely new facts (not derivable
    # from the résumé's plain skills list, which names tools but not a
    # self-assessed level), so these DO need a real .env value -- see
    # application_profile.py. Bare tool-name terms are intentionally
    # broad: every real listing seen so far phrases the question as
    # either "qual seu nível de X" or "possui conhecimento em X", and a
    # short, honest level answer ("Avançado") is a reasonable response
    # to either phrasing.
    "excel_nivel": ["excel"],
    "sql_nivel": ["sql"],
    # 2026-09-14: "Power B.I" (a dot between B and I, real phrasing found
    # live at SUSEP's listing) doesn't contain the bare "power bi"
    # substring -- added as its own term rather than relying on it.
    "powerbi_nivel": ["power bi", "powerbi", "power b.i"],
    # 2026-09-14, real miss found live (InfoJobs, "Bolsista Graduando --
    # BI"): a bare "Possui Graduação Completa?" -- deliberately placed
    # AFTER "escolaridade" above so that field's own, more specific
    # "graduação completa ou em andamento" phrasing (a different,
    # longer-form question) keeps winning first when it's the one that
    # actually appears; this only catches the standalone question.
    "graduacao_completa": [
        "graduação completa",
        "graduacao completa",
        # 2026-09-14, real miss found live (InfoJobs, "Assistente de
        # Dados -- Revenue Management"): the same in-progress/completed
        # fact, phrased as an open either/or question instead of yes/no.
        "cursando ensino superior ou já é formado",
        "cursando ensino superior ou ja e formado",
    ],
    # 2026-09-14: compiled after Nicholas had a separate assistant (with
    # web access to his public LinkedIn, cross-checked against his
    # résumé) draft real, honest answers -- including several honest
    # NEGATIVES ("0 anos de experiência com Marketing Mix Modeling", "não
    # tenho DBT listado") -- for a batch of real, live-blocked InfoJobs
    # listings' own screening questions. Every value below is real
    # content he reviewed and relayed, not fabricated by JARVIS -- same
    # basis as every other .env-backed field here. Deliberately narrow,
    # single-purpose fields (not a generic "answer bank") so a field
    # only ever fires for the specific real phrasing it was found under.
    "disponibilidade_estagio_09_16": ["das 09h00 às 16h00", "09h às 16h", "09h00 as 16h00"],
    "estatistica_matematica_financeira": ["estatística e matemática financeira", "estatistica e matematica financeira"],
    "call_center_experiencia": ["call center"],
    "power_query_dax": ["power query"],
    "power_automate_nivel": ["power automate"],
    "google_sheets_nivel": ["google planilhas avançado", "google planilhas avancado"],
    # 2026-09-14: covers both "experiência prévia com IA" style questions
    # AND "como você utiliza ferramentas de IA" style ones -- Nicholas's
    # real answer (a real internal local-AI tool he built for the
    # Auditoria Especial team, see [[project]] context) genuinely
    # answers either framing.
    "ia_experiencia": [
        "experiência prévia com inteligência artificial",
        "experiencia previa com inteligencia artificial",
        "experiência prévia com ia",
        "experiencia previa com ia",
        "utiliza ferramentas de ia",
        "utiliza ferramentas de inteligência artificial",
    ],
    "susep_conhecimento": ["trâmites da susep", "tramites da susep"],
    "txt_csv_conhecimento": ["arquivos txt, csv", "txt ou csv"],
    "kpis_comerciais_experiencia": ["kpis comerciais"],
    "indicadores_experiencia": [
        "experiência com indicadores e análises gerenciais",
        "experiencia com indicadores e analises gerenciais",
        # 2026-09-14, real miss found live (InfoJobs, "Digitalização de
        # Processos"): same underlying fact, worded as a from-scratch
        # question instead.
        "estruturou indicadores",
    ],
    "projeto_automacao_digitalizacao": [
        "atuou com automação ou digitalização",
        "atuou com automacao ou digitalizacao",
        "projeto de automação ou digitalização",
        "projeto de automacao ou digitalizacao",
        # 2026-09-14, real miss found live (InfoJobs, "Analista de
        # Automação de Dados"): same story, worded as "experiência com
        # automação de processos" instead.
        "experiência com automação de processos",
        "experiencia com automacao de processos",
    ],
    "experiencia_setores_diversos": [
        "empresas de tecnologia, consultorias, recursos humanos, varejo, finanças",
        "empresas de tecnologia, consultorias, recursos humanos, varejo, financas",
    ],
    # General, reusable fact -- unlike the two Ânima-specific fields
    # below, being a Politically Exposed Person (or not) doesn't depend
    # on which company is asking.
    "pep_status": ["pessoa politicamente exposta"],
    # 2026-09-14, real compliance/conflict-of-interest block found live
    # at TWO real Ânima Educação listings (UAM Mooca, Soluções) --
    # deliberately scoped to Ânima's own exact phrasing (requires "Ânima
    # Educação" in the matched text), unlike parentes_na_empresa/
    # pep_status above which are genuinely company-agnostic facts. Real
    # answers Nicholas gave for these two specific listings, not a
    # general-purpose "conflict of interest" field for any company.
    "anima_vinculo_comercial": ["parceira da ânima", "parceira da anima"],
    "anima_clt_historico": ["colaborador(a) clt da ânima educação", "colaborador(a) clt da anima educacao"],
    # 2026-09-14: the same underlying fact ("open to a fixed-term/
    # temporary contract") asked two different real ways.
    "disponibilidade_temporario": ["contrato temporário", "contrato temporario", "vaga temporária", "vaga temporaria"],
    "ferramentas_analise_dominadas": ["ferramentas de análise você domina", "ferramentas de analise voce domina"],
    "ferramentas_visualizacao_dominadas": [
        "ferramentas de visualização você domina",
        "ferramentas de visualizacao voce domina",
    ],
    "como_constroi_dashboards": [
        "como você constrói seus relatórios",
        "como voce constroi seus relatorios",
        # 2026-09-14, real miss found live (InfoJobs, "Analista
        # Estratégia Comercial"): same real fact (his own dashboard-
        # building work), worded as a bare "possui vivência" instead.
        "vivência com construção de dashboards",
        "vivencia com construcao de dashboards",
    ],
    "resultado_real_dados": [
        "resultado real que você gerou com dados",
        "resultado real que voce gerou com dados",
    ],
    "diferencial_analista": ["seu diferencial como analista de dados"],
    "atividades_vaga_experiencia": ["experiência com as atividades da vaga", "experiencia com as atividades da vaga"],
    "etl_ferramentas_experiencia": ["ferramentas etl"],
    "python_dbt_conhecimento": ["ou dbt"],
    "contas_pagar_receber": ["contas a pagar", "contas a receber"],
    "dre_relatorios_financeiros": ["dre e relatórios financeiros", "dre e relatorios financeiros"],
    "tecnologia_area_financeira": [
        "tecnologia aplicada à área financeira",
        "tecnologia aplicada a area financeira",
    ],
    "analise_dados_financeiros": [
        "análise de dados financeiros",
        "analise de dados financeiros",
    ],
    "mmm_experiencia": ["marketing mix modeling"],
    "inteligencia_mercado_experiencia": ["inteligência de mercado", "inteligencia de mercado"],
    "market_share_indicadores": ["market share"],
    "relatorios_executivos_experiencia": ["apresentações executivas", "apresentacoes executivas"],
    "crm_experiencia": ["utilizou crm", "crm em sua rotina"],
    "looker_apps_script": ["google apps script"],
    "python_dados_nivel": [
        "python ou outras linguagens de programação aplicadas",
        "python ou outras linguagens de programacao aplicadas",
    ],
    "melhoria_continua_exemplo": ["melhoria contínua que você implementou", "melhoria continua que voce implementou"],
    # 2026-09-14: the same "does your degree area fit" question, seen in
    # two real phrasings across two different listings.
    "graduacao_area_tecnica": [
        "engenharia, economia, administração, ciências exatas",
        "engenharia, economia, administracao, ciencias exatas",
        "áreas de exatas, computação e correlatas",
        "areas de exatas, computacao e correlatas",
    ],
    "mestrado_concluido": ["concluiu seu mestrado", "concluiu o mestrado"],
    # Deliberately LAST in this dict: a generic "tell me about your
    # experience" catch-all, real content but real risk of shadowing a
    # more specific field if checked too early -- classify_question_field
    # returns the FIRST match by dict order, so every field above (which
    # covers the exact same real listings' OWN more specific questions)
    # must keep winning first; this only ever fires when nothing more
    # specific matched.
    "conte_sua_experiencia": [
        "nos conte a respeito da sua experiência",
        "nos conte a respeito da sua experiencia",
        "comente brevemente suas experiência",
        "comente brevemente suas experiencia",
    ],
}
# RG/CPF and the other identity-verification fields (issuing authority,
# parents' names, birthplace) -- the exact class of data this project
# refused to capture or store since its very first design decision.
# Filling these from a local, Nicholas-controlled file
# (application_profile.py) is a deliberate, explicitly-confirmed
# exception to that original rule, not an oversight -- see that
# module's docstring for the full reasoning and the safeguards that
# keep the actual values out of every log/evidence path regardless.
_HARD_PII_FIELDS = {"rg", "rg_orgao_estado", "cpf", "nome_mae", "nome_pai", "naturalidade"}
# Blocks, but has no fillable field at all -- birth date specifically
# (see the _FIELD_TERMS comment above for why it's excluded).
_UNFILLABLE_HARD_STOP_TERMS = ["data de nascimento"]


def _matches_any_term(question_text: str, terms: list[str]) -> bool:
    haystack = question_text.lower()
    return any(re.search(rf"\b{re.escape(term)}\b", haystack) for term in terms)


def apply_resume_backed_profile_fields(profile: dict[str, str | None], resume: Resume) -> None:
    """Fills profile fields sourced from the résumé's own public data
    (data/resume.json) rather than the confidential .env file -- mutates
    `profile` in place, only ever filling a field that's still None
    (never overwrites a real .env value Nicholas set explicitly).
    Shared between gupy.py and infojobs.py (both call this with their
    own already-loaded `profile`/`resume`) so a résumé fact resolves the
    same way regardless of which site is asking for it -- infojobs.py
    had none of this at all before 2026-09-14, a real gap (linkedin/
    nome_completo/disponibilidade_inicio_imediato questions on InfoJobs
    were blocking unnecessarily for want of a lookup gupy.py already had).

    - "linkedin"/"nome_completo" -- not secrets, already public on his
      résumé/LinkedIn profile (2026-08-21).
    - "disponibilidade_inicio_imediato" -- only resolved for the
      explicit "immediate" status; any other value is a real, different
      answer this shouldn't guess at (2026-08-21).
    - "telefone"/"curso_nome"/"ingles_nivel"/"portfolio_link"/
      "graduacao_completa" -- added 2026-09-14, real gaps found live
      across a batch of blocked InfoJobs listings ("Informe seu número
      de WhatsApp", "Qual o nome do seu curso...", "Qual o nível do seu
      conhecimento em Inglês?", "Link do seu portfólio", "Possui
      Graduação Completa?") -- all already on the résumé (Nicholas had a
      separate Claude instance, with access to his OneDrive résumé,
      confirm these), just never wired up to answer a company's own
      screening question before."""
    if not profile.get("linkedin"):
        resume_linkedin = resume.personal_info.links.linkedin
        if resume_linkedin:
            profile["linkedin"] = resume_linkedin
    if not profile.get("nome_completo"):
        profile["nome_completo"] = resume.personal_info.full_name
    if profile.get("disponibilidade_inicio_imediato") is None:
        if resume.job_preferences.availability.status == "immediate":
            profile["disponibilidade_inicio_imediato"] = "Sim"
    if not profile.get("telefone") and resume.personal_info.phone:
        profile["telefone"] = resume.personal_info.phone
    if not profile.get("curso_nome") and resume.education:
        edu = resume.education[0]
        parts = [edu.degree.pt, f"({edu.institution})"]
        if profile.get("semestre_formatura"):
            parts.append(f"-- {profile['semestre_formatura']}")
        profile["curso_nome"] = " ".join(parts)
    if not profile.get("ingles_nivel"):
        for lang in resume.languages:
            if lang.name in ("English", "Inglês", "Ingles") and lang.proficiency:
                # 2026-09-14, real gap found live (InfoJobs batch): a
                # bare level string ("Intermediário-avançado...") never
                # matches a closed Sim/Não radio's whole-word fallback --
                # only questions phrased as an open "qual seu nível"
                # worked. "Sim. " prefix (same fix applied to excel_
                # nivel/sql_nivel/powerbi_nivel) makes it answer either
                # shape correctly.
                level = lang.proficiency.replace("Upper-Intermediate", "Intermediário-avançado")
                profile["ingles_nivel"] = f"Sim. {level}"
                break
    if not profile.get("portfolio_link"):
        links = resume.personal_info.links
        resolved_link = links.portfolio or links.github
        if resolved_link:
            profile["portfolio_link"] = resolved_link
    if not profile.get("graduacao_completa") and resume.education:
        status = resume.education[0].status
        if status == "in_progress":
            note = profile.get("semestre_formatura")
            profile["graduacao_completa"] = f"Não -- {note}" if note else "Não, ainda cursando"
        elif status == "completed":
            profile["graduacao_completa"] = "Sim"


def classify_question_field(question_text: str) -> str | None:
    """Returns which known, fillable field (see _FIELD_TERMS above) a
    screening question is asking about, or None if it's not one of the
    ones JARVIS knows how to look up locally. A birth-date question also
    returns None here (it's recognized by question_requires_stop()/
    is_hard_pii_question() below, but never gets a fillable field)."""
    haystack = question_text.lower()
    for field, terms in _FIELD_TERMS.items():
        if any(re.search(rf"\b{re.escape(term)}\b", haystack) for term in terms):
            return field
    return None


def detect_level(text: str) -> str:
    """Classifies a job listing's own level from its title/text --
    "estagio"/"pleno"/"junior" (default when neither is signaled).
    Drives which of the three salary figures (see application_profile.py)
    gets filled into a "pretensão salarial" question -- Nicholas's
    explicit request (2026-08-17): different numbers for estágio, junior,
    and pleno. Checked in this order (estágio and pleno are the specific
    signals; anything else defaults to junior, matching his own actual
    level) -- also matches the "Pl." abbreviation, a real gap found live
    (a "Engenheiro de Dados Pl." listing reached the apply flow despite
    job_matching.py's _SENIOR_EXCLUSION_TERMS only checking the spelled-
    out "pleno")."""
    haystack = text.lower()
    if re.search(r"\bestágio\b|\bestagio\b|\bestagiári?[ao]\b|\bestagiári?a\b", haystack):
        return "estagio"
    if re.search(r"\bpleno\b|\bpl\b", haystack):
        # \bpl\b (not \bpl\.?\b): a trailing "." is itself a non-word
        # character, so requiring a \b *after* an optional "." would
        # never match at end-of-string -- confirmed live testing this
        # against the real title "Engenheiro de Dados Pl.".
        return "pleno"
    return "junior"


def _strip_accents(text: str) -> str:
    """Same NFKD-then-ASCII approach as catho.py's _slugify -- Gupy's real
    gate text reads "...na empresa Itaú Unibanco." (accented), while a
    contact key typed by hand is more naturally the unaccented "itau" --
    normalizing both sides to compare is simpler and more robust than
    keeping two spellings in sync per contact."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def find_referral_contact(company: str | None, contacts: dict[str, dict[str, str]]) -> dict[str, str] | None:
    """Matches a job listing's company name against Nicholas's real,
    named referral contacts (jarvis.sites.application_profile's
    load_referral_contacts(), keyed by a short company identifier --
    e.g. "itau"/"santander"/"xp") -- whole-word match, same discipline
    as company_tier()'s _matches_known_name (a bare substring match on a
    short key like "xp" would false-positive on all sorts of unrelated
    words). Both sides are accent-stripped first -- a real bug caught
    live: the unaccented key "itau" does NOT whole-word-match the real,
    accented "Itaú Unibanco" gate text, since "itaú" and "itau" aren't
    the same substring at all. Returns the {"name": ..., "email": ...}
    dict for the first matching key, or None if this specific company
    isn't one Nicholas named a real contact for -- added 2026-08-19
    after he named three real people at three real companies who
    already know him and are willing to refer him."""
    if not company:
        return None
    haystack = _strip_accents(company.lower())
    for key, contact in contacts.items():
        if re.search(rf"\b{re.escape(_strip_accents(key.lower()))}\b", haystack):
            return contact
    return None


def is_hard_pii_question(question_text: str) -> bool:
    """True for genuine government ID/birth date questions (RG, CPF,
    data de nascimento) -- reported to Nicholas with a distinct, stronger
    message than other sensitive questions. RG/CPF are fillable from the
    local profile if he's set them there (application_profile.py); birth
    date has no fill path at all, ever."""
    field = classify_question_field(question_text)
    if field in _HARD_PII_FIELDS:
        return True
    return _matches_any_term(question_text, _UNFILLABLE_HARD_STOP_TERMS)


def question_requires_stop(question_text: str) -> bool:
    """True if a screening question's text mentions PII (RG/CPF/birth
    date/marital status) or a financial specific (current salary/salary
    expectation) -- confirmed live 2026-08-12/13 against two real,
    different Gupy listings' actual custom questions (Itaú: RG +
    remuneração; BIP Brasil: pretensão salarial + culture-fit). A hard
    stop when no locally-provided value exists for the field, not a
    warning. Deliberately biased toward over-triggering -- a false-
    positive stop just means "ask Nicholas," which is always the safe
    failure mode here, unlike, say, company_tier()'s substring-match
    bug, where a false positive was actively misleading."""
    return classify_question_field(question_text) is not None or is_hard_pii_question(question_text)


@dataclass
class ApplicationQuestion:
    """One question encountered while walking a real job-application
    flow -- logged whether it was safely auto-answered (Gupy's own
    standard referral questions) or caused a stop (any company-specific
    question, unconditionally -- see module note above). is_hard_pii
    distinguishes "JARVIS must never even receive this" (RG/CPF/birth
    date) from other sensitive-but-relayable questions (salary,
    culture-fit) for clearer reporting -- both currently cause the same
    stop, but the reason shown to Nicholas differs."""

    text: str
    answered: bool
    answer: Any = None
    is_hard_pii: bool = False


@dataclass
class ApplicationPreview:
    """Result of walking as far into a real job-application flow as
    requested -- the apply-flow equivalent of ChangePreview/
    preview_changes() above. preview_application() (read-only) NEVER
    submits anything and NEVER sets submitted=True. can_submit meant
    "reached a clean state with nothing blocking submission" and was
    permanently False for a long time because the real final submit
    step had never been reached live -- that changed 2026-08-19: a
    real, human-supervised, explicitly-confirmed submission (Gupy,
    Integra CSC, via continue_application_with_profile(finalize=True))
    reached the real "Finalizar candidatura" button and got back a
    genuine "Candidatura finalizada!" confirmation. submitted is the
    stricter, more honest field for that: True only when this specific
    run actually clicked a real submit button AND received a real
    confirmation back, not just "nothing is blocking it."."""

    site_name: str
    job_url: str
    can_submit: bool
    blocked_reason: str | None
    questions: list[ApplicationQuestion] = field(default_factory=list)
    summary_text: str = ""
    submitted: bool = False


class SiteAdapter(ABC):
    """One adapter per job site. Implementations live in
    sites/<site_name>.py (e.g. sites/gupy.py), each backed by
    Playwright with its own persistent, isolated browser profile."""

    site_name: str

    @abstractmethod
    def check_session(self) -> SessionStatus:
        """Verifies the persisted, authenticated browser context is still
        valid. Never attempts to log in itself -- that's always a manual,
        one-time step performed by the user in a real browser window."""

    @abstractmethod
    def inspect_current_profile(self) -> SiteProfileSnapshot:
        """Read-only: scrapes what the site currently shows. No writes."""

    @abstractmethod
    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        """Maps the canonical résumé's fields onto this site's own field
        names/edit UI. Site-specific field-mapping logic lives entirely
        here -- the canonical Resume schema stays site-agnostic."""

    @abstractmethod
    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        """Dry run: renders the diff for human review. Submits nothing."""

    @abstractmethod
    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        """The only method allowed to mutate site state. Must refuse
        (return applied=False, error set) unless confirmed=True, which the
        caller sets only after the user has explicitly approved the output
        of preview_changes(). Implementations should capture a screenshot
        or log entry as evidence of success/failure for the audit trail."""
