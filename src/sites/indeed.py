"""Fifth real SiteAdapter implementation, after Gupy, (paused) Vagas.com,
Catho, and InfoJobs -- see sites/base.py for the hard rules every
adapter here follows (manual login only, apply_changes refuses without
confirmed=True, dry-run always comes first).

Login URL found live on br.indeed.com's own homepage (see
config.py's INDEED_LOGIN_URL comment) -- the "Acessar" link, not
"Entrar"/"Login" as on the other sites. Same pattern as Catho:
Playwright reaches it fine headed, but headless=True gets served a 403
"Blocked - Indeed.com" page (confirmed live), so every open_context()
call in this file hardcodes headless=False, deliberately ignoring
config.SITES_HEADLESS -- same trade-off as catho.py.

Everything past login -- the profile edit page's real URL, its field
selectors, the actual save mechanism -- is intentionally NOT filled in
yet, same reasoning as every other adapter here: no way to find those
without an authenticated session, so they get discovered and verified
live rather than guessed.

Job search (search_jobs(), added 2026-08-11): no login required --
confirmed live, a plain unauthenticated headed context browses
br.indeed.com/jobs?q=<query>&l=<location> fine (still headless=False,
same 403 constraint as everywhere else in this file). Listing cards are
`.job_seen_beacon`, each carrying Indeed's own `data-jk` attribute on the
title `<a>` -- a clean, ready-made external id, unlike every other
adapter here which had to parse or decode one out of a URL. The
"cleaner-looking" canonical `br.indeed.com/viewjob?jk=<id>` URL was
tried and confirmed live to 403 ("Security Check") when visited directly
without the search page's own referrer/session context -- so this uses
the real relative href straight off the search result instead of
constructing a shorter one, same principle as never guessing a cleaner
URL than what the site actually serves.

**Escalating block, confirmed live 2026-08-11:** after several automated
searches in a short window (a handful of search_jobs() calls across a
few keywords), this machine's IP started getting a 403 "Security Check"
page from Indeed on EVERY request -- confirmed with a plain `curl`
carrying a normal browser User-Agent, so this isn't a Playwright/
automation-specific flag, it's a real IP-level block. Same posture as
Vagas.com (sites/vagas.py): step back, don't escalate into
evasion (rotating IPs, spoofing more headers, slowing down to sneak
under a rate limit). search_jobs() here works and is tested, but treat
Indeed as unreliable for now -- don't retry it repeatedly in a short
window, and if it starts 403ing, stop and let the user know rather than
hammering it."""

from __future__ import annotations

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

SITE_NAME = "indeed"


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    (see the module docstring) -- currently just checks that navigating to
    the login page itself doesn't stay on secure.indeed.com's auth flow."""
    from config import INDEED_LOGIN_URL

    page = context.new_page()
    try:
        page.goto(INDEED_LOGIN_URL, timeout=45_000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        return "secure.indeed.com" not in page.url
    finally:
        page.close()


class IndeedAdapter(SiteAdapter):
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
        manual step the CLI's `indeed-login` command calls. Returns whether
        the session actually verified as authenticated afterward."""
        from config import INDEED_LOGIN_URL

        return session.login_interactively(self.site_name, INDEED_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(
            "Ainda não implementado -- o profile edit page real (URL e seletores) precisa "
            "ser inspecionado numa sessão autenticada de verdade primeiro. Rode "
            "`python src/cli.py indeed-login` e me avise para eu inspecionar a página."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def search_jobs(self, query: str, *, location: str = "São Paulo") -> list[JobListing]:
        """Read-only, no login required (see module docstring) -- callers
        should run the result through jarvis.sites.job_matching before
        treating it as "matches". Only the first results page (~15 items)
        is fetched -- pagination is out of scope for this round."""
        import urllib.parse

        params = urllib.parse.urlencode({"q": query, "l": location})
        url = f"https://br.indeed.com/jobs?{params}"

        p, context = session.open_context(self.site_name, headless=False)
        try:
            page = context.new_page()
            page.goto(url, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            consent_btn = page.query_selector('button:has-text("Recusar tudo")')
            if consent_btn is not None and consent_btn.is_visible():
                consent_btn.click()
                page.wait_for_timeout(500)
            cards = self._extract_listing_cards(page)
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
            () => Array.from(document.querySelectorAll('.job_seen_beacon')).map(c => {
                const a = c.querySelector('h3.jobTitle a[data-jk]');
                const company = c.querySelector('[data-testid="company-name"]');
                const location = c.querySelector('[data-testid="text-location"]');
                return {
                    external_id: a ? a.getAttribute('data-jk') : null,
                    title: a ? (a.querySelector('span[title]')?.textContent || a.textContent || '').trim() : null,
                    href: a ? a.getAttribute('href') : null,
                    company: company ? company.textContent.trim() : null,
                    location: location ? location.textContent.trim() : null,
                };
            })
            """
        )


def _card_to_job_listing(card: dict) -> JobListing | None:
    if not card.get("title") or not card.get("href") or not card.get("external_id"):
        return None
    href = card["href"]
    url = href if href.startswith("http") else f"https://br.indeed.com{href}"
    return JobListing(
        site_name=SITE_NAME,
        external_id=card["external_id"],
        title=card["title"],
        company=card.get("company"),
        location=card.get("location"),
        url=url,
    )
