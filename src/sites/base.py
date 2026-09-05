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
    "nome_mae": ["nome da mãe", "nome da mae"],
    "nome_pai": ["nome do pai"],
    "naturalidade": ["naturalidade"],
    "raca_cor": ["raça", "raca", "cor da pele", "etnia"],
    "pcd": ["pessoa com deficiência", "pessoa com deficiencia", "pcd"],
    "salary_expectation": [
        "remuneração",
        "remuneracao",
        "salário",
        "salario",
        "pretensão salarial",
        "pretensao salarial",
        "renda",
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
    "cargo_atual": ["qual é o seu cargo atual", "qual e o seu cargo atual", "cargo atual"],
    "parentes_na_empresa": [
        "possui parentes que trabalham",
        "tem parentesco com algum colaborador",
        "possui parentesco com algum colaborador",
        # 2026-08-21, real miss found live (Vivo): "você tem parente(s)"
        # is the same nepotism-disclosure question, worded differently.
        "você tem parente",
        "voce tem parente",
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
    # 2026-08-21, real miss found live (Vivo): "nome completo, sem
    # abreviações" -- resolved from the résumé's own personal_info.
    # full_name, not a separate .env value (same reasoning as
    # "linkedin" -- it's not confidential, it's already on the résumé).
    "nome_completo": ["nome completo, sem abreviações", "nome completo sem abreviações", "nome completo, sem abreviacoes"],
    "semestre_formatura": [
        "semestre e o ano previstos para a conclusão do curso",
        "semestre e o ano previstos para a conclusao do curso",
        "previsão de formatura",
        "previsao de formatura",
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
