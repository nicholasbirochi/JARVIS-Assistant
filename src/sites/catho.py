"""Third real SiteAdapter implementation, after Gupy and (paused)
Vagas.com -- see sites/base.py for the hard rules every adapter
here follows (manual login only, apply_changes refuses without
confirmed=True, dry-run always comes first).

Login URL verified live (see config.py's CATHO_LOGIN_URL comment):
seguro.catho.com.br/login/ 301-redirects to catho.com.br/signin/, so the
latter is canonical. Playwright DOES reach this site, unlike Vagas.com --
but only headed: confirmed live that headless=True gets served a 403
"Forbidden" page (some bot-detection layer, not a hard connection reset
like Vagas.com's Cloudflare), while headless=False loads the real page
normally. Every open_context() call in this file hardcodes headless=False
because of that -- deliberately ignoring config.SITES_HEADLESS (which
still governs Gupy fine).

2026-08-19: also calls session.minimize_window() right after creating
its page so the required headed window doesn't visibly pop up over
whatever Nicholas is doing -- same real Chromium process/fingerprint
Catho's bot-check accepts, just minimized via a CDP command instead of
truly headless. (An earlier attempt at this launched Chromium with
--window-position=-32000,-32000 instead -- confirmed live that Chromium
silently ignores that flag, so it never actually worked; see
minimize_window()'s own docstring for how this one was verified for
real.)

Everything past login -- the profile edit page's real URL, its field
selectors, the actual save mechanism -- is intentionally NOT filled in
yet, same reasoning as Gupy/Vagas.com originally: no way to find those
without an authenticated session, so they get discovered and verified
live rather than guessed.

Job search (search_jobs(), added 2026-08-11): unlike profile editing,
Catho's job search needs NO login at all -- confirmed live, a plain
unauthenticated context browses results fine. Real URL pattern:
https://www.catho.com.br/vagas/<slug>/ where <slug> is the query
lowercased, accents stripped, non-alphanumerics collapsed to hyphens
(found by watching where the homepage's own search box navigates to,
same method as InfoJobs). A first-visit LGPD cookie-consent overlay
(`#lgpd-consent-widget`) blocks clicks on anything behind it until
dismissed via `button.acceptAll` -- confirmed live, not present on every
navigation (cookie-gated), so dismissal is conditional. Listing cards are
real `<article>` elements with clean, already-structured selectors
(`h2.title_offer a` for title/link, `p.mb-2 span.text-12` for company,
a `<p>` containing `.i_job_location` for the location text) -- no
truncated-snippet or double-counted-selector issues like InfoJobs had."""

from __future__ import annotations

import re
import unicodedata

from resume.schema import Resume
from sites import session
from sites.base import (
    ChangePreview,
    JobListing,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "catho"


def _slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    (see the module docstring) -- currently just checks that navigating to
    the login page itself doesn't stay there."""
    from config import CATHO_LOGIN_URL

    page = context.new_page()
    session.minimize_window(context, page)
    try:
        page.goto(CATHO_LOGIN_URL)
        page.wait_for_load_state("networkidle")
        return "signin" not in page.url
    finally:
        page.close()


class CathoAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        if not session.has_saved_session(self.site_name):
            return SessionStatus.NOT_LOGGED_IN

        p, context = session.open_context(self.site_name, headless=False)
        try:
            return SessionStatus.AUTHENTICATED if _is_authenticated(context) else SessionStatus.SESSION_EXPIRED
        except Exception:
            return SessionStatus.UNKNOWN_ERROR
        finally:
            context.close()
            p.stop()

    def login(self) -> bool:
        """Not part of the SiteAdapter interface (check_session() never logs
        in itself, by design) -- this is the explicit, separate, one-time
        manual step the CLI's `catho-login` command calls. Returns whether
        the session actually verified as authenticated afterward."""
        from config import CATHO_LOGIN_URL

        return session.login_interactively(self.site_name, CATHO_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(
            "Ainda não implementado -- o profile edit page real (URL e seletores) precisa "
            "ser inspecionado numa sessão autenticada de verdade primeiro. Rode "
            "`python src/cli.py catho-login` e me avise para eu inspecionar a página."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def search_jobs(self, query: str, *, max_results: int = 60) -> list[JobListing]:
        """Read-only, no login required (see module docstring) -- goes
        through session.open_context() anyway, same as every other
        adapter, even though there's no saved state to load for Catho
        search specifically; keeps this testable/consistent the same way
        as apply_changes() rather than a one-off raw Playwright call.
        headless=False, matching this file's confirmed 403-on-headless
        constraint everywhere else -- session.minimize_window() keeps
        that required window from popping up visibly (see its own
        docstring).

        Pagination: real, confirmed live -- page 1 is the bare
        /vagas/<slug>/ URL, page N>=2 is /vagas/<slug>/?page=N (found via
        the results page's own numbered pagination links). Stops once a
        page returns no new cards (real end of results) or max_results is
        reached, whichever comes first."""
        slug = _slugify(query)

        p, context = session.open_context(self.site_name, headless=False)
        try:
            page = context.new_page()
            session.minimize_window(context, page)
            cards: list[dict] = []
            page_num = 1
            while len(cards) < max_results:
                url = f"https://www.catho.com.br/vagas/{slug}/" if page_num == 1 else (
                    f"https://www.catho.com.br/vagas/{slug}/?page={page_num}"
                )
                page.goto(url, timeout=45_000, wait_until="domcontentloaded")
                page.wait_for_timeout(2500)
                consent_btn = page.query_selector("button.acceptAll")
                if consent_btn is not None and consent_btn.is_visible():
                    consent_btn.click()
                    page.wait_for_timeout(500)
                page_cards = self._extract_listing_cards(page)
                if not page_cards:
                    break
                cards.extend(page_cards)
                page_num += 1
                if page_num > 6:  # safety bound -- don't page forever
                    break
        finally:
            context.close()
            p.stop()

        listings = []
        for card in cards:
            listing = _card_to_job_listing(card)
            if listing is not None:
                listings.append(listing)
        return listings

    def _extract_listing_cards(self, page) -> list[dict]:
        """Raw card data, straight off the DOM -- kept as a thin, separate
        method so _card_to_job_listing()'s conversion/validation logic
        (below) can be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            """
            () => Array.from(document.querySelectorAll('article')).map(c => {
                const a = c.querySelector('h2.title_offer a');
                const company = c.querySelector('p.mb-2 span.text-12');
                const locP = Array.from(c.querySelectorAll('p')).find(p => p.querySelector('.i_job_location'));
                return {
                    external_id: a ? (a.getAttribute('href') || '').split('/').filter(Boolean).pop() : null,
                    title: a ? a.textContent.trim() : null,
                    href: a ? a.getAttribute('href') : null,
                    company: company ? company.textContent.trim() : null,
                    location: locP ? locP.textContent.trim().replace(/\\s+/g, ' ') : null,
                };
            })
            """
        )


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("href") or not card.get("external_id"):
        return None
    href = card["href"]
    url = href if href.startswith("http") else f"https://www.catho.com.br{href}"
    return JobListing(
        site_name=SITE_NAME,
        external_id=card["external_id"],
        title=card["title"],
        company=card.get("company"),
        location=card.get("location"),
        url=url,
    )
