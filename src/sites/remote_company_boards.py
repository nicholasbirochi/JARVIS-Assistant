"""Direct company career-board listings, added 2026-09-14 ("Quero vagas
da Super.com também e de empresas como essa!!"). Genuinely different
from btg_careers.py/amazon_jobs.py/ifood_careers.py: instead of one
adapter per company scraping that company's own bespoke site, this
covers MANY companies at once by talking to the two ATS platforms most
remote-first tech companies actually use for their public job board --
Ashby and Greenhouse -- both real, public, documented, unauthenticated
JSON APIs (same "no Playwright, no anti-bot layer" class as
remoteok.py/weworkremotely.py, confirmed live for every company below).

Real, live-confirmed investigation (2026-09-14) driving the company
list: Nicholas asked for "Super.com e empresas como essa". There are
TWO unrelated real companies both named "Super" -- Super.com (the
fintech/travel-savings app he meant, Ashby board) and Super Technologies
(an iGaming/sports-betting company, Greenhouse board, unrelated) --
confirmed distinct via a live fetch of each board's actual job titles.
Nicholas confirmed Super.com specifically, plus a curated list of
similar remote-first tech companies (his choice, offered as the
"Recomendado" option). Every company below was individually verified
live before being added -- several guesses (deel, wise, doist, toptal,
loom, automattic) were tried and DROPPED: some returned 404 (wrong
board token/company doesn't use that ATS publicly), one ("wise" on
Greenhouse) returned a real but completely unrelated company's jobs (18
"Supplemental Sales Agent" US insurance-sales roles, not Wise/
Transferwise) -- a real, confirmed false-match risk of guessing ATS
board tokens, not just a hypothetical one.

Companies confirmed live, real job counts fluctuate but the pattern
holds: Super.com (Ashby, `super.com`) -- data/analytics roles exist,
but current postings are geography-restricted to Canada/US, no Brazil
seen. Zapier (Ashby, `zapier`) -- smaller board, but at least one real
posting explicitly said "Americas (North, Central and South America)",
genuinely Brazil-inclusive. GitLab (Greenhouse, `gitlab`) -- 224 real
open roles, several Analytics/Analyst titles, mostly US/Canada/UK/
India, no Brazil confirmed on the specific roles seen. Canonical
(Greenhouse, `canonical`) -- 304 real open roles, several explicitly
"Home based - Worldwide" or "Home Based - Americas" (Canonical's own
public hiring policy is famously country-agnostic "home-based"
employment, the strongest real Brazil-inclusive signal of the four).

None of these confirms *guaranteed* Brazil eligibility for every single
posting -- this module surfaces the real location text on every listing
(never rewritten/summarized) precisely so Nicholas can judge each one
himself, same "surface real data, let him decide" principle as every
other adapter here (is_remote()/is_full_remote() already do the same
kind of best-effort classification, not a hard guarantee).

Adding another company later is a one-line addition to _COMPANIES below
(ats="ashby"|"greenhouse", board_token from that company's own public
job-board URL) -- no new code needed, as long as the token is verified
live first (see the dropped-guesses paragraph above for why that step
matters).

Profile editing/application submission: out of scope, same as every
other search-only adapter here -- only search_jobs() is implemented."""

from __future__ import annotations

import html
import json
import re
import urllib.request
from urllib.error import URLError

from resume.schema import Resume
from sites.base import (
    ChangePreview,
    JobListing,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "remote_company_boards"
_REQUEST_TIMEOUT_SECONDS = 20
_OUT_OF_SCOPE = "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."

# ats: which public API shape to use. board_token: the exact slug from
# that company's own public job-board URL (jobs.ashbyhq.com/<token> or
# boards.greenhouse.io/<token>) -- see module docstring for how each was
# verified live, not guessed.
_COMPANIES: list[dict[str, str]] = [
    {"name": "Super.com", "ats": "ashby", "board_token": "super.com"},
    {"name": "Zapier", "ats": "ashby", "board_token": "zapier"},
    {"name": "GitLab", "ats": "greenhouse", "board_token": "gitlab"},
    {"name": "Canonical", "ats": "greenhouse", "board_token": "canonical"},
]


def _strip_html(text: str) -> str:
    """Both APIs return HTML (Ashby: descriptionHtml/descriptionPlain
    already plain; Greenhouse: content, HTML-ENTITY-ESCAPED on top of
    that, e.g. literal "&lt;div&gt;" -- confirmed live) -- unescape
    entities first, then strip tags, same class of minimal hand-rolled
    stripper as remoteok.py's own (no new dependency for plain-text
    snippet material that's never rendered anywhere)."""
    return re.sub(r"<[^>]+>", " ", html.unescape(text))


def _fetch_json(url: str) -> dict | None:
    """Never raises: a network failure or malformed response returns
    None, matching every other adapter's fail-soft-per-source behavior
    (one company's board being briefly down must not sink the other
    three)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT_SECONDS) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _fetch_ashby_jobs(company_name: str, board_token: str) -> list[JobListing]:
    """Real, confirmed-live shape: https://api.ashbyhq.com/posting-api/
    job-board/<token> -> {"jobs": [{id, title, location, isRemote,
    jobUrl, descriptionPlain, ...}]}. `external_id` is prefixed with the
    board_token since ids are only unique WITHIN one company's board,
    not across the several boards this module combines."""
    data = _fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{board_token}")
    if data is None:
        return []
    listings = []
    for job in data.get("jobs") or []:
        job_id = job.get("id")
        title = job.get("title")
        job_url = job.get("jobUrl")
        if not job_id or not title or not job_url:
            continue
        location = job.get("location") or None
        snippet = (job.get("descriptionPlain") or "")[:600].strip() or None
        listings.append(
            JobListing(
                site_name=SITE_NAME,
                external_id=f"{board_token}:{job_id}",
                title=title,
                company=company_name,
                location=location,
                url=job_url,
                snippet=snippet,
            )
        )
    return listings


def _fetch_greenhouse_jobs(company_name: str, board_token: str) -> list[JobListing]:
    """Real, confirmed-live shape: https://boards-api.greenhouse.io/v1/
    boards/<token>/jobs?content=true -> {"jobs": [{id, title, location:
    {name}, absolute_url, content, ...}]}."""
    data = _fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true")
    if data is None:
        return []
    listings = []
    for job in data.get("jobs") or []:
        job_id = job.get("id")
        title = job.get("title")
        job_url = job.get("absolute_url")
        if not job_id or not title or not job_url:
            continue
        location = (job.get("location") or {}).get("name") or None
        snippet = _strip_html(job.get("content") or "")[:600].strip() or None
        listings.append(
            JobListing(
                site_name=SITE_NAME,
                external_id=f"{board_token}:{job_id}",
                title=title,
                company=company_name,
                location=location,
                url=job_url,
                snippet=snippet,
            )
        )
    return listings


_FETCHERS = {"ashby": _fetch_ashby_jobs, "greenhouse": _fetch_greenhouse_jobs}


def fetch_all_companies() -> list[JobListing]:
    """Fetches every registered company's full board -- small enough
    (four companies, each a single lightweight JSON GET) that there's no
    real cost to always fetching everything and letting local relevance
    filtering (job_matching.is_relevant_match(), same as every other
    adapter here) do the actual narrowing, rather than trying to filter
    server-side per company (neither API's query params were
    investigated for this -- unnecessary complexity for four sources)."""
    listings: list[JobListing] = []
    for company in _COMPANIES:
        fetcher = _FETCHERS[company["ats"]]
        listings.extend(fetcher(company["name"], company["board_token"]))
    return listings


class RemoteCompanyBoardsAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        # Public APIs, no login exists for this adapter.
        return SessionStatus.AUTHENTICATED

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError(_OUT_OF_SCOPE)

    def search_jobs(self, query: str, *, max_results: int = 200) -> list[JobListing]:
        """Read-only, no login required (see module docstring). query is
        accepted for interface consistency but has no effect -- neither
        API was found to have a useful server-side text filter worth
        relying on for just four companies; local relevance filtering
        does the real narrowing, same as ifood_careers.py/
        btg_careers.py."""
        return fetch_all_companies()[:max_results]
