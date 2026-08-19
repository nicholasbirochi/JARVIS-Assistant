"""BTG Pactual's own careers site (carreiras.btgpactual.com), added
2026-08-19 during the same "empresas com site próprio" push as
amazon_jobs.py/ifood_careers.py -- confirmed live: 100 real open
positions, all loaded on the /vagas listing page with no pagination
(scrolled 10x, count stayed at 100).

Real, live-confirmed findings:
- Listing page: https://carreiras.btgpactual.com/vagas -- lists every
  currently open position, unfiltered (no working query-string search
  found or attempted; same reasoning as ifood_careers.py -- this
  adapter fetches the full list once and relies entirely on this
  project's own local relevance filtering).
- No login required -- public page. Real note: the page never reaches
  Playwright's "networkidle" (some continuous background network
  activity) -- a plain wait_for_timeout is used instead, same as the
  investigation that found this.
- No login required -- public page.
- Card structure (real, confirmed live): `<div class="card-job-content">`
  wraps `<h3 class="title"><a href="/vagas/<category>/<slug>/<id>">
  <title></a></h3>` and a sibling `<p class="subtitle"><location></p>`.
  Each job's link appears TWICE on the page (title link + a separate
  "Ver vaga" link to the same href) -- deduplicated by external_id.
- Every listing found here is naturally already "BTG Pactual" --
  company is hardcoded, not scraped, since this adapter only ever
  searches BTG's own site.
- NOT wired into the automatic find_matching_jobs() path yet -- same
  conservative reasoning as amazon_jobs.py/ifood_careers.py.
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

SITE_NAME = "btg_careers"
_COMPANY_NAME = "BTG Pactual"
_LISTING_URL = "https://carreiras.btgpactual.com/vagas"


def _extract_job_id(href: str | None) -> str | None:
    if not href:
        return None
    match = re.search(r"/vagas/[^/]+/[^/]+/(\d+)", href)
    return match.group(1) if match else None


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("href"):
        return None
    external_id = _extract_job_id(card["href"])
    if external_id is None:
        return None
    return JobListing(
        site_name=SITE_NAME,
        external_id=external_id,
        title=card["title"],
        company=_COMPANY_NAME,
        location=card.get("location"),
        url=card["href"],
    )


class BTGCareersAdapter(SiteAdapter):
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
        accepted for interface consistency but has no effect -- no
        working server-side filter was found, so this always fetches
        every open position and lets local relevance filtering do the
        work (same as ifood_careers.py)."""
        p, context = session.open_context(self.site_name, headless=True)
        try:
            page = context.new_page()
            page.goto(_LISTING_URL, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)  # never reaches networkidle -- confirmed live
            cards = self._extract_listing_cards(page)
        finally:
            context.close()
            p.stop()

        seen: set[str] = set()
        listings = []
        for card in cards:
            listing = _card_to_job_listing(card)
            if listing is None or listing.external_id in seen:
                continue
            seen.add(listing.external_id)
            listings.append(listing)
        return listings[:max_results]

    def _extract_listing_cards(self, page) -> list[dict]:
        """Raw card data, straight off the DOM -- kept as a thin, separate
        method so _card_to_job_listing()'s conversion/validation logic can
        be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('h3.title a')).map(a => {
                const details = a.closest('.job-details');
                const subtitle = details ? details.querySelector('.subtitle') : null;
                return {
                    title: a.textContent.trim(),
                    href: a.href,
                    location: subtitle ? subtitle.textContent.trim() : null,
                };
            })
            """
        )
