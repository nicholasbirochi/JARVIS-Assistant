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
# job_preferences.target_roles set -- derived from the "Programming"/
# "Data Analysis"/"BI & Analytics Tools" skill categories, which is what
# resume.json actually has today (see jarvis/resume/schema.py's
# SkillCategory). Widened 2026-08-11 at the user's explicit request to
# not search BI/Power BI tooling alone -- "Python"/"SQL" added so roles
# that use those without ever saying "BI" also surface (e.g. a listing
# titled "Analista de Dados" that only mentions Python/SQL in the body).
# core_term matching in is_relevant_match() still requires the listing to
# actually mention the term, so a bare "Python" search doesn't turn into
# an unfiltered firehose of unrelated backend-dev roles -- see that
# function's docstring for how the senior-exclusion filter still applies
# regardless of which term matched.
_DEFAULT_DATA_ANALYST_TERMS = ["Analista de Dados", "Business Intelligence", "Power BI", "Python", "SQL"]

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

# Listings explicitly RESERVED for a demographic Nicholas isn't part of
# ("não sou PCD, sou branco", 2026-08-19) -- Brazilian affirmative-
# action/quota postings, legally distinct hiring tracks he isn't
# eligible for. Deliberately requires the EXCLUSIVE-signaling phrase
# ("exclusiva"/"afirmativa"/"cota"), not just the bare presence of
# "PCD"/"negro"/"negra" -- a real, confirmed-live distinction: "Vaga
# também para PcD" (Itaú's Tech Lead listing) means the role is open to
# everyone, PCD candidates included, and must NOT be excluded, while
# "Vaga Afirmativa para Pessoa com Deficiência (PCD)" and "(Afirmativa
# para Pessoas Negras)" are real, exclusive quota postings he should
# never see in his own results, let alone apply to.
#
# 2026-08-19, same day, widened further ("sem vagas PCD ou LGBTQI+ e
# demais minorias... sou branco padrão"): LGBTQI+-exclusive and
# women-exclusive tracks added, same exclusive-signaling-phrase
# discipline -- he isn't part of those demographics either. Also covers
# a SECOND real phrasing confirmed live the same day (Banco BV's own
# listings, found during the Rochaverá lookup): "banco de candidatura
# para <demografia>" ("BV com Elas" for women, "BV fora do armário" for
# LGBTQIAP+, "BV Além da Cota" for PCD) -- a real-world exclusive signal
# distinct from "vaga afirmativa"/"exclusiva", not assumed to be the
# only phrasing every company uses.
_AFFIRMATIVE_ACTION_EXCLUSIVE_TERMS = [
    "vaga afirmativa",
    "afirmativa para pessoa",
    "afirmativa para pessoas",
    "exclusiva para pcd",
    "exclusiva pcd",
    "vaga exclusiva pcd",
    "exclusiva para pessoas com deficiência",
    "exclusiva para pessoas com deficiencia",
    "exclusiva para pessoas negras",
    "exclusiva para pessoas pretas",
    "cota racial",
    "cota para negros",
    "cota para pessoas negras",
    "exclusiva para lgbtqia+",
    "exclusiva para lgbtqi+",
    "exclusiva para pessoas lgbtqia+",
    "afirmativa para pessoas lgbtqia+",
    "afirmativa para lgbtqia+",
    "afirmativa lgbtqia+",
    "cota lgbtqia+",
    "exclusiva para mulheres",
    "afirmativa para mulheres",
    "afirmativa feminina",
    "cota para mulheres",
    "cota feminina",
    "banco de candidatura para mulheres",
    "banco de candidatura para pessoas negras",
    "banco de candidatura para pcd",
    "banco de candidatura para lgbtqia+",
    "banco de candidatura para lgbtqiap+",
]


def is_affirmative_action_only(title: str, snippet: str | None = None) -> bool:
    """True if a listing is explicitly reserved for a demographic
    Nicholas isn't part of -- see _AFFIRMATIVE_ACTION_EXCLUSIVE_TERMS
    above for the real, confirmed-live distinction from a merely
    inclusive listing."""
    haystack = f"{title} {snippet or ''}".lower()
    return any(term in haystack for term in _AFFIRMATIVE_ACTION_EXCLUSIVE_TERMS)


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
# the opposite side of the metro region (Guarulhos, Barueri, Jundiaí,
# etc.) even though they showed up in real search results -- the user
# asked to focus, not to keep everything "sort of near SP".
#
# Osasco and Cajamar added 2026-08-13, a narrow, explicit exception to
# the rule above: real bigtech listings (Amazon) kept showing up there
# specifically, and the user confirmed he wants them counted as "perto
# de você" -- Osasco borders São Paulo city directly (much closer than
# Guarulhos/Barueri, which stay excluded), and Cajamar is a real,
# recurring Amazon logistics/data hub in this project's own search
# results, not an arbitrary addition.
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
    "osasco",
    "cajamar",
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

    if is_affirmative_action_only(title, snippet):
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


# "home office pra gringa" (2026-08-11): fully-remote roles, typically at
# LatAm-staffing companies serving international clients (BairesDev is a
# real, recurring example already seen live in Catho results, titled
# "Trabalhe de Casa"/"Work From Home" in mixed PT/EN). Two separate
# signals rather than one: REMOTE_TERMS alone just means "not commuting
# anywhere" (could easily be a normal Brazilian company's WFH policy);
# INTERNATIONAL_TERMS (foreign currency, "global"/"international" framing)
# is what actually suggests "pra gringa" specifically, so listings get
# tagged differently depending on which signals are present rather than
# guessing "remote" always means "international".
_REMOTE_TERMS = [
    "100% remoto",
    "totalmente remoto",
    "remoto",
    "home office",
    "trabalhe de casa",
    "work from home",
    "remote",
]
_INTERNATIONAL_TERMS = [
    "us$",
    "usd",
    "dólar",
    "dolar",
    "international",
    "internacional",
    "global",
    "worldwide",
]

# "internacional, somente full home-office" (2026-08-14): a listing that
# says "remoto" but ALSO signals a hybrid/partial-onsite arrangement
# isn't the fully-remote role Nicholas actually wants -- explicit
# request to stop counting those as real home office. Checked against
# every remote listing (not just international ones), since a hybrid
# role mislabeled as "home office" is equally wrong for a purely
# national remote search.
_HYBRID_TERMS = ["híbrido", "hibrido", "hybrid"]


def is_remote(title: str, snippet: str | None, location: str | None = None) -> bool:
    haystack = f"{title} {snippet or ''} {location or ''}".lower()
    return any(term in haystack for term in _REMOTE_TERMS)


def is_full_remote(title: str, snippet: str | None, location: str | None = None) -> bool:
    """is_remote() plus a real refinement: a listing that also mentions
    "híbrido"/"hybrid" isn't full home office, even if it separately says
    "remoto" somewhere (mixed/inconsistent listing text, seen live) --
    Nicholas's explicit request, see the _HYBRID_TERMS comment above."""
    if not is_remote(title, snippet, location):
        return False
    haystack = f"{title} {snippet or ''} {location or ''}".lower()
    return not any(term in haystack for term in _HYBRID_TERMS)


def has_international_signal(title: str, snippet: str | None) -> bool:
    haystack = f"{title} {snippet or ''}".lower()
    return any(term in haystack for term in _INTERNATIONAL_TERMS)


def filter_remote(listings: list[JobListing]) -> list[JobListing]:
    """Full home-office only (is_full_remote(), not the looser
    is_remote()) -- a hybrid role never belongs in the "home office"
    list Nicholas asked for."""
    return [listing for listing in listings if is_full_remote(listing.title, listing.snippet, listing.location)]


# "foque em trabalhos de bancos e bigtechs e startup" (2026-08-12) --
# three named lists, each checked the same way: a company either matches
# a known name or it doesn't, never a guess/elimination heuristic. An
# earlier version of the startup category tried to approximate it as
# "not bank/bigtech and not an obvious staffing agency" -- that matched
# ~84% of every real result and wasn't a meaningful filter, replaced here
# with a real, curated list.
_BANK_COMPANIES = [
    "itaú",
    "itau",
    "bradesco",
    "santander",
    "banco do brasil",
    "caixa econômica",
    "caixa economica",
    "btg pactual",
    "banco pan",
    "safra",
    "banco votorantim",
    "daycoval",
    "banco modal",
    "banco bmg",
    "banco sofisa",
    "credit suisse",
    "jpmorgan",
    "jp morgan",
    "goldman sachs",
    "hsbc",
    "citibank",
    "banco abc",
    "banrisul",
    # 2026-08-19, "MELHORE AINDA MAISSSSS! TEM MUITO POUCAS OPÇÕES DE
    # EMPRESAS" -- substantially widened every company tier, not just
    # this one. Banco BV confirmed real and relevant live the same day
    # (Rochaverá address lookup turned up an actual "Coordenação de
    # Engenharia de Dados" opening there).
    "banco bv",
    "sicoob",
    "sicredi",
    "banco do nordeste",
    "banestes",
    "mercantil do brasil",
    "banco bs2",
    "banco fibra",
    "banco alfa",
    "deutsche bank",
    "morgan stanley",
    "barclays",
    "bnp paribas",
    # 2026-08-19, round 3 ("foque bastante em colocar bancos!! e
    # fintechs!!!"). "ing bank" (not bare "ing" -- that 3-letter
    # fragment appears inside dozens of ordinary English words like
    # "banking"/"training", the exact class of false positive this
    # project has already been bitten by once).
    "banco pine",
    "banco master",
    "banco rendimento",
    "banco ourinvest",
    "novo banco continental",
    "standard chartered",
    "scotiabank",
    "ing bank",
    "bank of america",
    "rabobank",
    "société générale",
    "societe generale",
    "mizuho",
    "sumitomo mitsui",
]

# Digital-native financial-tech companies -- added as its own tier
# 2026-08-17 at the user's explicit request ("quero Fin techs também
# agora!"), split out of _BANK_COMPANIES/_BIGTECH_COMPANIES/
# _STARTUP_COMPANIES rather than left folded in: Nubank/Banco Inter/C6
# Bank/etc. are meaningfully different from a traditional full-license
# bank like Itaú/Bradesco even though some (Nubank, C6) are themselves
# licensed banks -- the real distinguishing line here is "financial
# product as a tech company," which is exactly the category he's asking
# to see separately. Stone moved here from _BIGTECH_COMPANIES (it's a
# payments fintech, not a general tech platform -- being publicly traded
# was the reason it was grouped with TOTVS/VTEX before, but that reason
# alone doesn't make it "bigtech"; Nubank is also publicly traded and was
# never bigtech). Cora/Ebanx/Creditas/Justos/Conta Simples/Contabilizei
# moved here from _STARTUP_COMPANIES for the same reason -- they're
# financial-services companies first, not general-purpose startups.
_FINTECH_COMPANIES = [
    "nubank",
    "banco inter",
    "c6 bank",
    "original",
    "neon",
    "picpay",
    "will bank",
    "banco next",
    "xp investimentos",
    "stone",
    "cora",
    "ebanx",
    "creditas",
    "justos",
    "conta simples",
    "contabilizei",
    "mercado pago",
    "pagseguro",
    "pagbank",
    "toro investimentos",
    "warren investimentos",
    "genial investimentos",
    "ame digital",
    "iugu",
    # 2026-08-19 expansion (see _BANK_COMPANIES's note just above).
    "agibank",
    "dock pagamentos",
    "celcoin",
    "getnet",
    "cielo",
    "clear corretora",
    "modalmais",
    "qi tech",
    "asaas",
    "pagar.me",
    "dlocal",
    "recargapay",
    # 2026-08-19, round 2: found by actually inspecting that day's live
    # "outras" results for real companies the wider lists still missed
    # (not guessed) -- "XP Inc." doesn't contain the phrase "xp
    # investimentos" already listed above, so bare "xp" is needed too
    # (same whole-word-match safety already proven live for this exact
    # short key -- see base.py's find_referral_contact tests). Capco and
    # B3 are real, confirmed-present financial-services companies.
    "xp",
    "capco",
    "b3",
    # 2026-08-19, round 3 ("foque bastante em colocar bancos!! e
    # fintechs!!!"). "ton" (Stone's own product) deliberately left out
    # -- too short/generic a fragment (collides with unrelated words) to
    # match safely the way the other short keys here ("xp", "b3") were
    # already proven safe against with real regression tests.
    "superdigital",
    "infinitepay",
    "zoop",
    "meliuz",
    "bxblue",
    "nexoos",
    "bitso",
    "mercado bitcoin",
    "foxbit",
    "novadax",
    "órama investimentos",
    "orama investimentos",
    "rico investimentos",
    "easynvest",
    "konduto",
    "guiabolso",
    "mobills",
    "organizze",
    "finanzero",
    "credihome",
    # 2026-08-21, round 3 -- same technique, inspecting that day's real
    # "outras" results. "fundo garantidor de créditos" (not the bare
    # "fgc" abbreviation) for the same short-key false-positive
    # reasoning as "ton" above.
    "núclea",
    "nuclea",
    "fundo garantidor de créditos",
    "fundo garantidor de creditos",
]

# Established, large, mostly publicly-traded tech companies -- global
# giants plus the handful of Brazilian tech platforms that are genuinely
# "big" by any normal measure (headcount, market cap, years operating),
# as opposed to _STARTUP_COMPANIES below (younger, VC-funded scale-ups).
# The line between the two lists is a real judgment call, not a precise
# classification -- Stone/TOTVS/VTEX are publicly traded, which is the
# concrete reason they're here and not in the startup list.
_BIGTECH_COMPANIES = [
    "google",
    "microsoft",
    "amazon",
    "meta platforms",
    "apple",
    "netflix",
    "ibm",
    "oracle",
    "sap",
    "salesforce",
    "nvidia",
    "intel",
    "adobe",
    "uber",
    "airbnb",
    "spotify",
    "mercado livre",
    "mercadolivre",
    "ifood",
    "totvs",
    "vtex",
    # 2026-08-19, "cade o google? IBM?" -- both were already here (see
    # above); what was actually missing is that no CURRENT listing from
    # them matched that day's search (confirmed, not a list bug -- see
    # the same date's startup-tier investigation). Widened the list
    # anyway since it really was thin: databricks/snowflake added given
    # they're literally in the résumé's own target_roles/skills, plus
    # the big global tech-consultancies that hire heavily for data
    # roles in Brazil.
    "dell technologies",
    "cisco",
    "servicenow",
    "snowflake",
    "databricks",
    "grupo globo",
    "magazine luiza",
    "magalu",
    "locaweb",
    "uol",
    "accenture",
    "deloitte",
    "capgemini",
    "thoughtworks",
    "globant",
    "ci&t",
    # 2026-08-19, round 2: found by actually inspecting that day's live
    # "outras" results -- these were real companies with real listings
    # that the first widening pass still missed, not guesses. "vem pra
    # vivo" is Vivo/Telefônica's own recruiting campaign brand, used
    # sidesteps the false-positive risk of bare "vivo" (an ordinary
    # Portuguese word) while still catching their real listings.
    "infosys",
    "dxc technology",
    "tata consultancy services",
    "avanade",
    "stefanini",
    "t-systems",
    "keyrus",
    "serasa experian",
    "vem pra vivo",
    "ibope",
    "cogna educação",
    "cogna educacao",
    # 2026-08-21, round 3: same technique, inspecting that day's real
    # "outras" results again -- these are real, high-scale companies
    # the earlier rounds still missed.
    "whirlpool",
    "doordash",
    "globo",
    "gft technologies",
    "mixpanel",
    "wpp media",
    "rd saúde",
    "rd saude",
    "larsen & toubro",
]

# Real, named Brazilian startups/scale-ups -- a genuine list (same
# "matches or it doesn't" principle as banks/bigtechs), not the earlier
# elimination-based guess ("not bank/bigtech and not a staffing agency",
# which matched ~84% of everything and wasn't a meaningful filter). Skews
# toward data/analytics-relevant ones (Semantix, Indicium, Datarisk,
# Neoway, Take Blip, Pipefy) given the résumé's own focus, alongside the
# better-known consumer unicorns/scale-ups. "bairesdev" added 2026-08-12,
# found live: a real, VC-backed LatAm dev-staffing scale-up, and the
# single largest source of genuinely relevant, remote, junior-friendly
# Python/Power BI listings ("Trabalhe de Casa"/"Work From Home") in this
# project's own search results -- directly on point for the user's own
# "home office pra gringa" request, not an arbitrary addition.
_STARTUP_COMPANIES = [
    "bairesdev",
    "rappi",
    "quinto andar",
    "quintoandar",
    "creditas",
    "gympass",
    "movile",
    "hotmart",
    "loft",
    "wildlife studios",
    "olist",
    "contaazul",
    "conta azul",
    "rd station",
    "resultados digitais",
    "facily",
    "merama",
    "madeiramadeira",
    "madeira madeira",
    "printi",
    "petlove",
    "buser",
    "sami",
    "alice saude",
    "alice saúde",
    "take blip",
    "pipefy",
    "jusbrasil",
    "gupy",
    "docket",
    "sallve",
    "inloco",
    "in loco",
    "unico",
    "kovi",
    "cargox",
    "frete.com",
    "neoway",
    "datarisk",
    "semantix",
    "indicium",
    # 2026-08-19 expansion (see _BANK_COMPANIES's note above).
    "nuvemshop",
    "loggi",
    "housi",
    "trocafone",
    "enjoei",
    "elo7",
    "mottu",
    "indrive",
    "solfácil",
    "solfacil",
    "sympla",
    "wellhub",
    "vindi",
    "superlógica",
    "superlogica",
    "omie",
    "bling",
    "cobli",
    "cerc",
    "provu",
    "cashme",
    # 2026-08-21, round 3 -- same technique, inspecting that day's real
    # "outras" results.
    "tractian",
]


def _matches_known_name(haystack: str, names: list[str]) -> bool:
    """Whole-word match, not a bare substring -- the real bug found live
    (2026-08-12) building the bank/bigtech/startup lists: "CADERNO
    INTELIGENTE" matched _BIGTECH_COMPANIES's "intel" (Intel Corp) as a
    substring of "INTELIGENTE", and "REDE ANCORA" matched a startup
    list's "cora" (the fintech Cora, now in _FINTECH_COMPANIES) as a
    substring of "ANCORA" -- neither company has anything to do with the
    real Intel or Cora. Same class of bug as is_relevant_match's
    "BI"/"recebimento" false positive, fixed the same way: \\b word
    boundaries."""
    return any(re.search(rf"\b{re.escape(name)}\b", haystack) for name in names)


def company_tier(company: str | None) -> str | None:
    """"banco"/"fintech"/"bigtech"/"startup" if the company name matches a
    known one from the lists above, else None -- never guesses on an
    unrecognized name. Checked in that order -- fintech before bigtech/
    startup so a company that could arguably fit either (Stone is both
    publicly traded AND a payments fintech) lands in the more specific,
    more useful category for Nicholas's own request (2026-08-17)."""
    if not company:
        return None
    haystack = company.lower()
    if _matches_known_name(haystack, _BANK_COMPANIES):
        return "banco"
    if _matches_known_name(haystack, _FINTECH_COMPANIES):
        return "fintech"
    if _matches_known_name(haystack, _BIGTECH_COMPANIES):
        return "bigtech"
    if _matches_known_name(haystack, _STARTUP_COMPANIES):
        return "startup"
    return None


_TIER_ORDER = {"banco": 0, "fintech": 1, "bigtech": 2, "startup": 3}


def rank_bank_bigtech_first(listings: list[JobListing]) -> list[JobListing]:
    """Stable sort: known banks first, then fintechs, then bigtechs, then
    startups, everything else last -- relative order within each group is
    preserved."""

    def sort_key(listing: JobListing) -> int:
        tier = company_tier(listing.company)
        return _TIER_ORDER.get(tier, 4)

    return sorted(listings, key=sort_key)


def group_by_tier(listings: list[JobListing], *, include_other: bool = False) -> dict[str, list[JobListing]]:
    """Buckets listings into "banco"/"fintech"/"bigtech"/"startup" via
    company_tier(). With include_other=False (the original behavior),
    listings whose company doesn't match any known name are dropped
    entirely. With include_other=True (added 2026-08-17 at the user's
    explicit request for real volume -- "quero pelo menos mais de 200
    vagas" -- the named-company tiers alone are gated by real, current
    market openings at ~100 curated companies, which will never reach
    that on their own no matter how much more searching happens), a
    fifth "outras" bucket holds every OTHER relevant listing instead of
    silently dropping it -- still real, still matches every other
    restriction (skill relevance, level, location/remote), just at a
    company not in the curated lists. Each bucket is ranked junior-first
    the same way run_job_search() ranks its own lists."""
    buckets: dict[str, list[JobListing]] = {tier: [] for tier in _TIER_ORDER}
    if include_other:
        buckets["outras"] = []
    for listing in listings:
        tier = company_tier(listing.company)
        if tier in buckets:
            buckets[tier].append(listing)
        elif include_other:
            buckets["outras"].append(listing)
    return {tier: rank_junior_first(items) for tier, items in buckets.items()}


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
