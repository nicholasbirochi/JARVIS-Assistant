"""LinkedIn -- read-only job search only. See sites/base.py's module
docstring for the original reasoning (real, well-documented account-
restriction risk from LinkedIn's anti-automation infrastructure -- rate
limiting, CAPTCHA, behavioral fingerprinting -- disproportionate to what
this project needs); the user also already updates their own LinkedIn
profile manually and explicitly confirmed early on they didn't want that
automated.

Revisited 2026-08-11 at the user's explicit request, scoped narrowly:
search_jobs() only, after directly confirming with the user that this
means an isolated Playwright login profile (same pattern as every other
adapter here), NOT their real daily-driver browser -- Playwright has no
way to read an already-running browser's saved cookies/sessions anyway.

inspect_current_profile/build_update_plan/preview_changes/apply_changes
are deliberately NOT "not implemented yet" like the other adapters' early
skeletons -- they're permanently out of scope for this site specifically,
and raise a distinct message saying so, per base.py's explicit guidance:
"If LinkedIn is ever revisited, restrict it to check_session/
preview_changes only -- never wire apply_changes for it."

Job search (search_jobs(), added 2026-08-12): real URL, found live by
using the site's own top-nav search box rather than guessing:
https://www.linkedin.com/jobs/search-results/?keywords=<query>. Listing
cards are genuinely harder to scrape than the other four adapters here
-- LinkedIn's markup uses hashed, build-specific class names throughout
(e.g. `_6f09d0c0 c9837f6e ...`), a real anti-scraping-flavored signal
even if not the primary intent, so nothing here selects on those classes
at all. Instead: every card-ish element carries a `componentkey`
attribute ending in `-<jobId>` (confirmed live); the SHORTEST such
element per unique jobId that still contains at least two blank-line
(`\n\n`) separators is the actual card text block, cleanly parseable as
title / company / location. (The shortest-without-that-guard heuristic
was tried first and picked a tiny badge element with just the company
name as text for one real card -- the two-separator check is the actual
fix, not a nicety.) No stable per-card href exists (cards are click-
handler-driven, updating a `currentJobId` query param rather than
linking out) -- but /jobs/view/<jobId>/ is a real, confirmed direct URL
once the id is known.

Given this is the highest-risk site in this project (see base.py) and
its DOM is comparatively fragile/likely to drift, search_jobs() here
stays deliberately low-volume (no pagination, default max_results caps
at whatever a single results page returns, ~25) rather than pushed as
hard as the other four -- and is still NOT wired into
job_search.py's automatic, unattended find_matching_jobs() tool.
Same reasoning as never automating profile edits here: an unattended,
repeated automatic search is exactly the kind of unsupervised use that
risk profile argues against.

2026-08-19: wired into job_portal/server.py's _portal_adapters()
-- but ONLY for the manually-triggered paths (the portal's own
"Atualizar vagas agora" button, and the first open of the portal),
NEVER for refresh_if_due()'s once-a-day unattended timer. Runs as an
anonymous guest (search_jobs() never checks/uses a saved session), so
this doesn't expose Nicholas's actual LinkedIn account to automation --
the residual risk is IP-level rate limiting on the public job-search
page, not account restriction, and it's kept out of the one path
(the unattended timer) where he wouldn't be around to notice or step in
if something looked off.

Also calls session.minimize_window() right after creating its page --
same fix as catho.py, see that module's docstring and
minimize_window()'s own for why the earlier --window-position attempt
never actually worked."""

from __future__ import annotations

import re

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

SITE_NAME = "linkedin"
_SEARCH_URL = "https://www.linkedin.com/jobs/search-results/"
_VERIFIED_BADGE_SUFFIX = " (Vaga verificada)"

_PROFILE_EDITING_OUT_OF_SCOPE = (
    "Edição de perfil no LinkedIn é intencionalmente fora de escopo (não é 'ainda não "
    "implementado') -- ver o docstring de linkedin.py e de sites/base.py. Só "
    "busca de vagas (search_jobs) é suportada aqui."
)


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    -- currently just checks that navigating to the login page itself
    doesn't stay there."""
    from config import LINKEDIN_LOGIN_URL

    page = context.new_page()
    session.minimize_window(context, page)
    try:
        page.goto(LINKEDIN_LOGIN_URL, timeout=45_000, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        return "/login" not in page.url
    finally:
        page.close()


class LinkedInAdapter(SiteAdapter):
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
        """Not part of the SiteAdapter interface -- the explicit, separate,
        one-time manual step the CLI's `linkedin-login` command calls.
        Isolated Playwright profile, same as every other adapter here."""
        from config import LINKEDIN_LOGIN_URL

        return session.login_interactively(self.site_name, LINKEDIN_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def search_jobs(self, query: str, *, max_results: int = 25) -> list[JobListing]:
        """Read-only -- callers should run the result through
        jarvis.sites.job_matching before treating it as "matches". No
        pagination, deliberately low-volume -- see module docstring.
        `max_results` accepted (not paginated against) so this matches
        every other adapter's search_jobs(query, *, max_results=...)
        signature -- 2026-08-19, needed to wire this into
        jarvis.job_portal.server's run_job_search() call convention,
        which always passes max_results as a keyword arg."""
        import urllib.parse

        url = f"{_SEARCH_URL}?{urllib.parse.urlencode({'keywords': query})}"

        p, context = session.open_context(self.site_name, headless=False)
        try:
            page = context.new_page()
            session.minimize_window(context, page)
            page.goto(url, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3500)
            cards = self._extract_listing_cards(page)
        finally:
            context.close()
            p.stop()

        listings = []
        for card in cards:
            listing = _card_to_job_listing(card)
            if listing is not None:
                listings.append(listing)
            if len(listings) >= max_results:
                break
        return listings

    def _extract_listing_cards(self, page) -> list[dict]:
        """Raw card data, straight off the DOM -- kept as a thin, separate
        method so _card_to_job_listing()'s conversion/validation logic
        (below) can be unit-tested without a real page.evaluate() call."""
        return page.evaluate(
            r"""
            () => {
                const byId = {};
                const elems = Array.from(document.querySelectorAll('[componentkey]'));
                for (const el of elems) {
                    const m = el.getAttribute('componentkey').match(/-(\d{6,})$/);
                    if (!m) continue;
                    const jobId = m[1];
                    const text = el.innerText || '';
                    if ((text.match(/\n\n/g) || []).length < 2) continue;
                    if (!byId[jobId] || text.length < byId[jobId].length) byId[jobId] = text;
                }
                return Object.entries(byId).map(([jobId, text]) => ({ jobId, text }));
            }
            """
        )


def _parse_card_text(text: str) -> dict[str, str | None]:
    """title/company/location out of the card's plain innerText -- see
    module docstring for the real, live-confirmed shape. Split on blank
    lines rather than any class-based selector, since none of LinkedIn's
    classes here are stable across builds."""
    segments = [s.strip() for s in text.split("\n\n") if s.strip()]
    title_block = segments[0] if segments else ""
    title = title_block.split("\n")[0].strip()
    if title.endswith(_VERIFIED_BADGE_SUFFIX):
        title = title[: -len(_VERIFIED_BADGE_SUFFIX)].strip()
    company = segments[1] if len(segments) > 1 else None
    location = segments[2] if len(segments) > 2 else None
    return {"title": title or None, "company": company, "location": location}


def _card_to_job_listing(card: dict) -> JobListing | None:
    job_id = card.get("jobId")
    text = card.get("text") or ""
    if not job_id or not re.fullmatch(r"\d{6,}", job_id):
        return None
    fields = _parse_card_text(text)
    if not fields["title"]:
        return None
    return JobListing(
        site_name=SITE_NAME,
        external_id=job_id,
        title=fields["title"],
        company=fields["company"],
        location=fields["location"],
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
    )
