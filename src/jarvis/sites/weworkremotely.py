"""We Work Remotely (weworkremotely.com) -- second international
remote-job source, added 2026-08-19 right after remoteok.py, same
motivation (the résumé's own English target_roles need an English-
language, remote-first source to actually land on). Genuinely simple
like remoteok.py: a real, public RSS feed (XML, stdlib
xml.etree.ElementTree, same approach as jarvis/assistant/news.py) -- no
Playwright/session.py, no login, no anti-bot layer.

Real, confirmed-live findings:
- Feed URL: https://weworkremotely.com/remote-jobs.rss -- the
  all-categories combined feed, ~100 most recent postings. A per-
  category feed also exists (e.g.
  categories/remote-full-stack-programming-jobs.rss, confirmed live),
  but there's no "data" category that actually resolves (categories/
  remote-data-jobs.rss 301-redirects to nowhere useful) -- rather than
  guess at WWR's exact category taxonomy, this fetches the general feed
  and relies entirely on this project's own local relevance filtering,
  same principle as every other adapter's own module docstring, and the
  same explicit tradeoff ifood_careers.py already made for the same
  reason (no working server-side filter to lean on).
- `query` is accepted for interface consistency with every other
  adapter's search_jobs() but has no effect on what's fetched (see
  above) -- calling this multiple times with different terms just
  re-fetches the same ~100-item feed each time; downstream dedupe()
  collapses the repeats. Same known, accepted inefficiency as
  ifood_careers.py, not a bug.
- Real, confirmed-live `<item>` shape: `<title>Company: Position</title>`
  (combined -- split on the FIRST ": " to separate them, confirmed
  live against real entries with a colon inside the company name itself,
  e.g. "Clari + Salesloft: Senior Director, Product & Strategy", which
  still splits correctly since only the first ": " is used),
  `<link>`/`<guid>` (both the real weworkremotely.com job page -- link
  used), `<region>` (location text, e.g. "Anywhere in the World"),
  `<description>` (raw HTML, stripped and used as snippet for local
  relevance matching, same as remoteok.py).

Every listing here is remote by the entire premise of this site --
same fix as remoteok.py: `region` is prefixed with "Remote" so
jarvis.sites.job_matching.is_remote()'s keyword matching actually
catches these (WWR's own region text, e.g. "Anywhere in the World",
doesn't literally say "remote").

Profile editing/application submission: out of scope, same as every
other search-only adapter here."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

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

SITE_NAME = "weworkremotely"
_FEED_URL = "https://weworkremotely.com/remote-jobs.rss"
_FETCH_TIMEOUT_SECONDS = 20
_OUT_OF_SCOPE = "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)


def _fetch_items() -> list[ET.Element]:
    """Raw feed fetch + XML parse -- never raises (no internet, feed
    unreachable, malformed XML, timeout all return []), same fail-soft
    contract as every other adapter's own network call here."""
    try:
        req = urllib.request.Request(_FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
            data = resp.read()
        root = ET.fromstring(data)
        return list(root.iter("item"))
    except (urllib.error.URLError, TimeoutError, ET.ParseError, OSError):
        return []


def _item_to_job_listing(item: ET.Element) -> JobListing | None:
    raw_title = item.findtext("title")
    link = item.findtext("link") or item.findtext("guid")
    if not raw_title or not link:
        return None

    # "Company: Position", confirmed live -- split on the FIRST ": "
    # only, so a company name that itself contains a colon (real
    # example seen live: "Clari + Salesloft: Senior Director...") still
    # separates correctly.
    company, sep, title = raw_title.partition(": ")
    if not sep:  # no colon at all -- not the expected shape, don't guess
        company, title = None, raw_title

    region = (item.findtext("region") or "").strip()
    # Honest, not fabricated -- every WWR listing is remote by
    # definition; its own region text ("Anywhere in the World") doesn't
    # literally say "remote", which would make this project's own
    # is_remote() miss it.
    location = f"Remote ({region})" if region else "Remote"

    description = item.findtext("description") or ""
    snippet = _strip_html(description)[:600].strip() or None

    return JobListing(
        site_name=SITE_NAME,
        external_id=link,
        title=title.strip(),
        company=company.strip() if company else None,
        location=location,
        url=link,
        snippet=snippet,
    )


class WeWorkRemotelyAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        # Public RSS feed, no login exists for this adapter.
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
        Playwright/browser involved -- a plain RSS/XML fetch. query has
        no effect on what's fetched (no working category filter to lean
        on -- see module docstring); local relevance filtering
        downstream does the real work, same as every other adapter."""
        items = _fetch_items()

        listings = []
        for item in items:
            listing = _item_to_job_listing(item)
            if listing is not None:
                listings.append(listing)
            if len(listings) >= max_results:
                break
        return listings
