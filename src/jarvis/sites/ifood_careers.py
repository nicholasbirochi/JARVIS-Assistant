"""iFood's own careers site (carreiras.ifood.com.br), added 2026-08-17
during the same "empresas com site próprio" push that added
amazon_jobs.py -- confirmed live: 96 real, open positions, ALL loaded on
a single page with no pagination at all (scrolled 6x, count stayed at
96 -- no lazy-loading either).

Real, live-confirmed findings:
- Listing page: https://carreiras.ifood.com.br/jobs/ -- lists every
  currently open position, unfiltered. `?search=`/`?query=` URL params
  (guessed, matching other sites' conventions) do NOT filter results --
  confirmed live, identical 96 links regardless. This adapter therefore
  fetches the full list once and relies entirely on this project's own
  local relevance filtering (jarvis.sites.job_matching) -- same as every
  other adapter here already does as a second pass, just without a
  first-pass site-side filter to also lean on.
- No login required -- public page.
- Card structure (real, confirmed live): `<a title="<clean job title>"
  href="/job/<id>/">` wrapping an `<h4>` (level: Sênior/Pleno/etc.) and
  an `<h5 class="...job-text-grey">` (location, e.g. "Brasil" or
  "Osasco, São Paulo, Brasil"). The `title` attribute is used directly
  (cleaner than the nested `<h3>`, which has a stray leading space).
- Every listing found here is naturally already "iFood" -- company is
  hardcoded, not scraped, since this adapter only ever searches iFood's
  own site.
- query is accepted for interface consistency with every other
  adapter's search_jobs() but has no effect on what's fetched (see
  above) -- calling this multiple times with different terms just
  re-fetches the same 96-listing page each time; downstream dedupe()
  collapses the repeats. A real, known inefficiency, not a bug -- fixing
  it would mean a fundamentally different (cached, single-fetch) calling
  convention than every other adapter here uses.
- NOT wired into the automatic find_matching_jobs() path yet -- same
  conservative reasoning as amazon_jobs.py.
- Profile editing/application submission: out of scope, same as every
  other site here -- only search_jobs() is implemented.
"""

from __future__ import annotations

import re

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

SITE_NAME = "ifood_careers"
_COMPANY_NAME = "iFood"
_LISTING_URL = "https://carreiras.ifood.com.br/jobs/"


def _extract_job_id(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"/job/(\d+)/", href)
    return match.group(1) if match else None


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("href"):
        return None
    external_id = _extract_job_id(card["href"])
    if external_id is None:
        return None
    title = card["title"]
    level = card.get("level")
    full_title = f"{title} ({level})" if level else title
    return JobListing(
        site_name=SITE_NAME,
        external_id=external_id,
        title=full_title,
        company=_COMPANY_NAME,
        location=card.get("location"),
        url=card["href"],
    )


class IFoodCareersAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        # Public listing page, no login exists for this adapter.
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

    def search_jobs(self, query: str, *, max_results: int = 100) -> list[JobListing]:
        """Read-only, no login required (see module docstring). query is
        accepted for interface consistency but has no effect -- the site
        has no working server-side filter, so this always fetches every
        open position and lets local relevance filtering do the work."""
        p, context = session.open_context(self.site_name, headless=True)
        try:
            page = context.new_page()
            page.goto(_LISTING_URL, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle", timeout=30_000)
            page.wait_for_timeout(2500)
            cards = self._extract_listing_cards(page)
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
        method so _card_to_job_listing()'s conversion/validation logic can
        be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('a[href*="/job/"]')).map(a => ({
                title: a.getAttribute('title'),
                href: a.href,
                level: (a.querySelector('h4') || {}).textContent || null,
                location: (a.querySelector('h5.job-text-grey') || a.querySelector('h5') || {}).textContent || null,
            }))
            """
        )
