"""Amazon's own careers site (amazon.jobs), added 2026-08-12 after
Nicholas pointed out that big companies often only list roles on their
own career site, not through aggregators like InfoJobs/Catho/Gupy/
LinkedIn -- confirmed live: a real, Brazil-based, relevant listing
("Analista Dados, Operações", Cajamar - SP) was NOT present anywhere in
this project's InfoJobs/Catho/Gupy/LinkedIn results.

Real, live-confirmed findings:
- Search URL: https://www.amazon.jobs/en/search?base_query=<query>&loc_query=<location>
  -- loc_query as a free-text "City, Country" string (e.g. "São Paulo,
  Brazil") reliably filters to that location; a `state=<name>` param
  tried first did NOT filter results (still returned jobs from Canada/
  US/Japan/etc.), so loc_query is the only real, working filter found.
- No login required -- public search, same as Catho/Gupy/InfoJobs
  search_jobs(). Still routed through jarvis.sites.session.open_context()
  for lifecycle consistency/testability, matching Catho's own reasoning
  (see catho.py) even though there's no saved session to load.
- Pagination: `&offset=N`, confirmed live -- N=10 returns a genuinely
  different page of results from N=0 (10 results per page).
- Card selector: `.job-tile`, title in the card's first `h3`, link on
  the card's own `<a>`, job id embedded in the URL's own `/jobs/<id>/`
  path segment.
- Every listing found here is naturally already "Amazon" -- company is
  hardcoded, not scraped, since this adapter only ever searches Amazon's
  own site.
- NOT wired into the automatic find_matching_jobs() path yet -- kept to
  manual/explicit use only until this adapter has run enough real
  searches to confirm it doesn't trigger the kind of automated-query
  blocking that got Indeed blocked earlier in this project.
- Profile editing/application submission: out of scope, same reasoning
  as every other site here -- only search_jobs() is implemented; the
  rest raise NotImplementedError rather than guess at a flow never
  inspected live.
"""

from __future__ import annotations

import re
import urllib.parse

from jarvis.resume.schema import Resume
from jarvis.sites import session
from jarvis.sites.base import (
    ChangePreview,
    JobListing,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "amazon_jobs"
_COMPANY_NAME = "Amazon"


def _extract_job_id(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"/jobs/(\d+)/", href)
    return match.group(1) if match else None


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("link"):
        return None
    external_id = _extract_job_id(card["link"])
    if external_id is None:
        return None
    return JobListing(
        site_name=SITE_NAME,
        external_id=external_id,
        title=card["title"],
        company=_COMPANY_NAME,
        location=card.get("location"),
        url=card["link"],
    )


class AmazonJobsAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        # Public search, no login exists for this adapter.
        return SessionStatus.AUTHENTICATED

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(
            "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError(
            "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."
        )

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError(
            "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."
        )

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError(
            "Este adapter só cobre busca de vagas -- edição de perfil não é objetivo aqui."
        )

    def search_jobs(
        self, query: str, *, max_results: int = 30, location: str = "São Paulo, Brazil"
    ) -> list[JobListing]:
        """Read-only, no login required (see module docstring). location
        is a free-text "City, Country" string passed straight through to
        loc_query -- defaults to this project's own target city, but
        callers can widen it (e.g. "Brazil") for a broader sweep.

        Pagination: real, confirmed live -- offset=0, 10, 20, ... each
        return a distinct page of up to 10 results. Stops once a page
        returns no new cards or max_results is reached, whichever comes
        first."""
        base_query = urllib.parse.quote(query)
        loc_query = urllib.parse.quote(location)

        p, context = session.open_context(self.site_name, headless=True)
        try:
            page = context.new_page()
            cards: list[dict] = []
            offset = 0
            while len(cards) < max_results:
                url = (
                    f"https://www.amazon.jobs/en/search?base_query={base_query}"
                    f"&loc_query={loc_query}&offset={offset}"
                )
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                page.wait_for_load_state("networkidle", timeout=30_000)
                page.wait_for_timeout(2500)
                page_cards = self._extract_listing_cards(page)
                if not page_cards:
                    break
                cards.extend(page_cards)
                offset += 10
                if offset > 100:  # safety bound -- don't page forever
                    break
        finally:
            context.close()
            p.stop()

        listings = []
        for card in cards:
            listing = _card_to_job_listing(card)
            if listing is not None:
                listings.append(listing)
        return listings[:max_results]

    def _extract_listing_cards(self, page) -> list[dict]:
        """Raw card data, straight off the DOM -- kept as a thin, separate
        method so _card_to_job_listing()'s conversion/validation logic
        can be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('.job-tile')).map(el => {
                const titleEl = el.querySelector('h3');
                const linkEl = el.querySelector('a');
                const locEl = el.querySelector('.location-and-id, [class*="location" i]');
                return {
                    title: titleEl ? titleEl.textContent.trim() : null,
                    link: linkEl ? linkEl.href : null,
                    location: locEl ? locEl.textContent.trim() : null,
                };
            })
            """
        )
