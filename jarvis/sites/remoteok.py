"""RemoteOK (remoteok.com) -- international remote-job board, added
2026-08-19 right after widening the résumé's own target_roles with
English terms (Machine Learning/Data Analyst/Data Engineer) specifically
to reach postings like these. Genuinely different from every other
adapter in this project: it's a real, public, documented JSON API
(https://remoteok.com/api) -- no Playwright/session.py needed at all, no
anti-bot layer to work around, no login, nothing to render. Confirmed
live: a plain HTTP GET with a normal browser User-Agent returns clean
JSON, no 403/blocking of any kind.

Query mapping: `tags=<slug>` (e.g. `tags=python`, `tags=data-analyst`)
IS a real, confirmed-live server-side filter -- two different tag
queries returned completely disjoint result sets (zero id overlap),
not the same static feed reshuffled. `query` is slugified the same way
catho.py's _slugify() does (lowercased, accents stripped, spaces to
hyphens) since RemoteOK's own tags follow that convention.

Real, confirmed-live data quality note, the reason this still goes
through this project's own is_relevant_match() rather than trusting the
tag filter alone (same principle as every other adapter's own module
docstring): tag-filtered results were still noisy -- e.g. `tags=python`
and `tags=engineer` both returned genuinely unrelated roles ("Shop
Assistant", "Aviation Maintenance Technician", "Fire Fighter") mixed in
with real matches ("Senior Data Engineer", "Data Analyst"). RemoteOK's
own filtering narrows the field, it doesn't replace local relevance
checking.

Response shape (real, confirmed live): a JSON array whose FIRST element
is a legal/attribution object (`{"legal": "...", "last_updated": ...}`),
not a job -- every other element has `id`/`position`(title)/`company`/
`location`/`url`/`tags`/`salary_min`/`salary_max`. Detected by checking
for `id`+`position` presence rather than hardcoding "skip index 0", in
case a future response ever omits the legal blob.

Every listing here is, by the entire premise of this site, a remote
position -- but RemoteOK's own `location` field is inconsistent (often
the company's home country/city, not literally the word "remote"),
which would make jarvis.sites.job_matching.is_remote()'s own keyword
matching miss most of them. Fixed by prefixing the stored location with
"Remote" (honest, not fabricated -- that's what listing on this site
means) rather than changing the shared is_remote() logic for one
adapter's quirk.

API Terms of Service (read live at the top of every response): asks
callers to link back to the real remoteok.com URL and credit RemoteOK
as the source, or risk having API access suspended -- satisfied by
construction here, since every listing's `url` already points straight
at the real remoteok.com job page (never rehosted or stripped).

Real, confirmed-live robustness note: one specific tag query
(`tags=sql`) returned genuinely malformed JSON (an unterminated string,
not a network truncation -- retried and got the same result) -- caught
explicitly rather than letting a single bad response crash the whole
search; returns an empty list for that one call instead, letting
run_job_search()'s own per-adapter try/except (which would have caught
it anyway) never even need to.

Profile editing/application submission: out of scope, same as every
other search-only adapter here (iFood/Amazon/BTG careers) -- only
search_jobs() is implemented."""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.request
from urllib.error import URLError

from jarvis.resume.schema import Resume
from jarvis.sites.base import (
    ChangePreview,
    JobListing,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "remoteok"
_API_URL = "https://remoteok.com/api?tags={tag}"
_REQUEST_TIMEOUT_SECONDS = 20
_OUT_OF_SCOPE = "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."


def _slugify_tag(query: str) -> str:
    normalized = unicodedata.normalize("NFKD", query).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def _fetch_listings(tag: str) -> list[dict]:
    """Raw HTTP GET + JSON parse -- kept as its own function so
    search_jobs()'s conversion/validation logic can be unit-tested
    without a real network call. Never raises: a network failure or
    malformed response (both confirmed to happen live, see module
    docstring) returns an empty list, matching every other adapter's
    fail-soft-per-term behavior."""
    url = _API_URL.format(tag=tag)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _strip_html(text: str) -> str:
    """RemoteOK's own `description` field is raw HTML -- a minimal
    tag-stripper (no new dependency, same reasoning as catho.py's own
    hand-rolled _slugify) rather than pulling in a full HTML parser for
    what's ultimately just used as plain-text snippet material for local
    relevance matching, not rendered anywhere."""
    return re.sub(r"<[^>]+>", " ", text)


def _card_to_job_listing(card: dict) -> JobListing | None:
    # The response's first element is a legal/attribution object, not a
    # job -- detected by required-field presence rather than a
    # hardcoded index (see module docstring).
    job_id = card.get("id")
    title = card.get("position")
    raw_url = card.get("url")
    if not job_id or not title or not raw_url:
        return None

    # Real gap found live: most listings' TITLE alone rarely repeats a
    # broader search term ("SQL", "Analytics") even when RemoteOK's own
    # tag filter matched it -- without the description as a snippet,
    # jarvis.sites.job_matching.is_relevant_match() had almost nothing
    # to check against and silently dropped nearly everything.
    description = card.get("description") or ""
    snippet = _strip_html(description)[:600].strip() or None

    location = card.get("location") or ""
    # Honest, not fabricated -- every listing on this site is remote by
    # definition; RemoteOK's own location field is inconsistent (often
    # the company's home city/country instead), which would make this
    # project's own is_remote() miss most of these otherwise.
    full_location = f"Remote ({location.strip()})" if location.strip() else "Remote"

    salary_min = card.get("salary_min") or 0
    salary_max = card.get("salary_max") or 0
    salary = f"US$ {salary_min:,} - US$ {salary_max:,}" if salary_min and salary_max else None

    return JobListing(
        site_name=SITE_NAME,
        external_id=str(job_id),
        title=title,
        company=card.get("company"),
        location=full_location,
        url=raw_url,
        snippet=snippet,
        salary=salary,
    )


def _cards_to_listings(cards: list[dict], max_results: int) -> list[JobListing]:
    listings = []
    for card in cards:
        listing = _card_to_job_listing(card)
        if listing is not None:
            listings.append(listing)
        if len(listings) >= max_results:
            break
    return listings


class RemoteOkAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        # Public API, no login exists for this adapter.
        return SessionStatus.AUTHENTICATED

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def search_jobs(self, query: str, *, max_results: int = 100) -> list[JobListing]:
        """Read-only, no login required (see module docstring). No
        Playwright/browser involved at all -- a plain JSON API call.
        `tags=<slugified query>` is a real, confirmed-live server-side
        filter, still run through this project's own is_relevant_match()
        downstream since it isn't a clean one on its own (see module
        docstring).

        Real, confirmed-live gap: RemoteOK's tag vocabulary is a fixed,
        narrower set than this project's own multi-word target_roles --
        "data-analyst" and "data-engineer" (the exact tags this résumé's
        own new English target_roles slugify to) both return zero real
        jobs (just the response's own always-present legal/attribution
        entry -- see module docstring), while the bare first word "data"
        alone returns 100 raw / 37 relevant. So a multi-word query that
        converts to zero real listings falls back to just its first word
        as a second tag try -- covers this project's own concrete,
        motivating case (Data Analyst/Data Engineer) without guessing at
        RemoteOK's full tag list."""
        listings = _cards_to_listings(_fetch_listings(_slugify_tag(query)), max_results)
        if not listings:
            words = query.strip().split()
            if len(words) > 1:
                listings = _cards_to_listings(_fetch_listings(_slugify_tag(words[0])), max_results)
        return listings
