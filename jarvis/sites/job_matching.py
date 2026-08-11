"""Site-agnostic job-search relevance logic -- keyword derivation from the
résumé and a local relevance filter, kept separate from any one site's
scraping code so it can be reused across adapters and tested without a
browser.

Real finding driving why this exists (InfoJobs, live, 2026-08-11): the
site's own free-text search is loose enough that a literal
"Analista de Dados Júnior" query returned zero actually-relevant listings
(finance/HR/warehouse roles matched purely on "Júnior"), while the shorter
"Analista de Dados" query returned genuinely relevant ones. So a site's own
search can't be trusted alone -- results still need a local relevance
check against the résumé before being called a "match"."""

from __future__ import annotations

import re

from jarvis.resume.schema import Resume
from jarvis.sites.base import JobListing

# Fallback search terms used only when the résumé has no explicit
# job_preferences.target_roles set -- derived from the "Data Analysis"/
# "BI & Analytics Tools" skill categories, which is what resume.json
# actually has today (see jarvis/resume/schema.py's SkillCategory). Kept
# deliberately short: broad enough to catch real listings (confirmed live),
# specific enough not to pull in unrelated "Analista" roles.
_DEFAULT_DATA_ANALYST_TERMS = ["Analista de Dados", "Business Intelligence", "Power BI"]

# Title/snippet signals that the role is above the résumé's actual level
# (current student, one internship completed + one in progress -- no
# full-time professional experience yet). Matched case-insensitively as
# whole-ish tokens, not substrings of unrelated words.
_SENIOR_EXCLUSION_TERMS = [
    "pleno",
    "sênior",
    "senior",
    " sr ",
    " sr.",
    "especialista",
    "coordenador",
    "coordenadora",
    "gerente",
    "gerência",
    "head de",
    "diretor",
    "diretora",
]

# Explicit junior/entry-level signals -- deliberately NOT folded into the
# search query itself (see module docstring: combining "Júnior" into the
# InfoJobs query made results worse, not better). Used only for local
# tagging/sorting after the fact.
_JUNIOR_SIGNAL_TERMS = [
    "júnior",
    "junior",
    " jr ",
    " jr)",
    " jr.",
    " jr-",
    "estágio",
    "estagiário",
    "estagiária",
    "trainee",
    "aprendiz",
]

# The user's home city (São Bernardo do Campo, from resume.json's
# personal_info.location) plus its immediate ABC-region neighbors, and
# São Paulo city itself ("Centro de SP e proximidades" per the user's own
# words, 2026-08-11) -- listing location strings almost never carry
# district-level detail (nearly everything just says "São Paulo - SP"),
# so the city itself is the finest resolution available, not "Centro"
# specifically. Deliberately does NOT include Grande São Paulo cities on
# the opposite side of the metro region (Guarulhos, Barueri, Osasco,
# Jundiaí, etc.) even though they showed up in real search results --
# the user asked to focus, not to keep everything "sort of near SP".
_TARGET_REGION_TERMS = [
    "são bernardo do campo",
    "sao bernardo do campo",
    "sbc",
    "são paulo",
    "sao paulo",
    "santo andré",
    "santo andre",
    "são caetano do sul",
    "sao caetano do sul",
    "diadema",
    "mauá",
    "maua",
    "ribeirão pires",
    "ribeirao pires",
    "rio grande da serra",
]


def derive_search_terms(resume: Resume) -> list[str]:
    """job_preferences.target_roles, if the user has ever set it, always
    wins -- it's an explicit statement of intent. Otherwise falls back to
    a short, data-analysis-specific term list; this fallback is a
    heuristic, not a general-purpose resume-to-role inference (see module
    docstring) -- it's only correct for a résumé like this one, whose
    skills are already data-analysis-flavored."""
    if resume.job_preferences.target_roles:
        return list(resume.job_preferences.target_roles)
    return list(_DEFAULT_DATA_ANALYST_TERMS)


def is_relevant_match(title: str, snippet: str | None, keywords: list[str]) -> bool:
    """True if the listing text actually mentions one of the search
    keywords' core topic (not just an incidental word overlap like
    "Júnior") AND doesn't look like a role above the résumé's level.

    Keyword matching: for a multi-word keyword (e.g. "Analista de Dados"),
    require the LAST word (the most specific term, "dados") to appear --
    this is what separates real matches from noise, confirmed live: a
    plain "Analista" match alone pulled in finance/HR/warehouse listings
    that have nothing to do with data. Matched on a whole-word boundary,
    not a bare substring -- a short acronym like "BI" (from "Power BI")
    would otherwise false-positive inside ordinary words like
    "recebimento" (confirmed live, a real false match before this fix)."""
    haystack = f"{title} {snippet or ''}".lower()

    if any(term in haystack for term in _SENIOR_EXCLUSION_TERMS):
        return False

    for keyword in keywords:
        core_term = keyword.strip().split()[-1].lower()
        if re.search(rf"\b{re.escape(core_term)}\b", haystack):
            return True
    return False


def filter_relevant(listings: list[JobListing], keywords: list[str]) -> list[JobListing]:
    return [listing for listing in listings if is_relevant_match(listing.title, listing.snippet, keywords)]


def has_junior_signal(title: str, snippet: str | None) -> bool:
    """True if the listing explicitly says júnior/jr/estágio/trainee/
    aprendiz. False doesn't mean "not junior" -- plenty of real entry-level
    postings never state a level at all -- it just means the signal isn't
    there to sort on."""
    haystack = f"{title} {snippet or ''}".lower()
    return any(term in haystack for term in _JUNIOR_SIGNAL_TERMS)


def rank_junior_first(listings: list[JobListing]) -> list[JobListing]:
    """Stable sort: listings with an explicit junior/estágio/trainee signal
    first, everything else (already senior-filtered, just unlabeled) after
    -- relative order within each group is preserved, so a site's own
    "Relevantes" ranking still matters as the tiebreaker."""
    return sorted(listings, key=lambda listing: not has_junior_signal(listing.title, listing.snippet))


def is_in_target_region(location: str | None, region_terms: list[str] = _TARGET_REGION_TERMS) -> bool:
    """True if the listing's location text names the user's home city, its
    ABC-region neighbors, or São Paulo city itself. False for anything
    with no location text at all -- an unknown location isn't a match,
    it's just unknown, and shouldn't be assumed nearby."""
    if not location:
        return False
    haystack = location.lower()
    return any(term in haystack for term in region_terms)


def filter_by_location(
    listings: list[JobListing], region_terms: list[str] = _TARGET_REGION_TERMS
) -> list[JobListing]:
    return [listing for listing in listings if is_in_target_region(listing.location, region_terms)]


def dedupe(listings: list[JobListing]) -> list[JobListing]:
    """Keeps first occurrence per (site_name, external_id) -- searching
    multiple keyword variants against the same site will legitimately
    return the same real listing more than once."""
    seen: set[tuple[str, str]] = set()
    result = []
    for listing in listings:
        key = (listing.site_name, listing.external_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(listing)
    return result
