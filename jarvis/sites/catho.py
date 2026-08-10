"""Third real SiteAdapter implementation, after Gupy and (paused)
Vagas.com -- see jarvis/sites/base.py for the hard rules every adapter
here follows (manual login only, apply_changes refuses without
confirmed=True, dry-run always comes first).

Login URL verified live (see jarvis/config.py's CATHO_LOGIN_URL comment):
seguro.catho.com.br/login/ 301-redirects to catho.com.br/signin/, so the
latter is canonical. Playwright DOES reach this site, unlike Vagas.com --
but only headed: confirmed live that headless=True gets served a 403
"Forbidden" page (some bot-detection layer, not a hard connection reset
like Vagas.com's Cloudflare), while headless=False loads the real page
normally. Every open_context() call in this file hardcodes headless=False
because of that -- deliberately ignoring config.SITES_HEADLESS (which
still governs Gupy fine), since a browser window popping up for every
preview/apply run is the real, working trade-off here, not a bug.

Everything past login -- the profile edit page's real URL, its field
selectors, the actual save mechanism -- is intentionally NOT filled in
yet, same reasoning as Gupy/Vagas.com originally: no way to find those
without an authenticated session, so they get discovered and verified
live rather than guessed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from jarvis.resume.schema import Resume
from jarvis.sites import session
from jarvis.sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "catho"


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    (see the module docstring) -- currently just checks that navigating to
    the login page itself doesn't stay there."""
    from jarvis.config import CATHO_LOGIN_URL

    page = context.new_page()
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
        from jarvis.config import CATHO_LOGIN_URL

        return session.login_interactively(self.site_name, CATHO_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(
            "Ainda não implementado -- o profile edit page real (URL e seletores) precisa "
            "ser inspecionado numa sessão autenticada de verdade primeiro. Rode "
            "`python -m jarvis catho-login` e me avise para eu inspecionar a página."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")
