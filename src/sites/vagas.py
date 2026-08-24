"""PAUSED -- see config.py's VAGAS_LOGIN_URL comment. Confirmed
live: Vagas.com sits behind Cloudflare and resets the connection outright
for Playwright's automated browser, even headed with the webdriver flag
hidden -- a stronger anti-automation signal than Gupy's. Per this
project's own LinkedIn precedent (sites/base.py), that's a reason
to step back, not to escalate into stealth/evasion techniques. Left at
login/check_session only, same as LinkedIn -- do not wire
inspect_current_profile/apply_changes for this site without revisiting
that decision explicitly.
"""

from __future__ import annotations

from resume.schema import Resume
from sites import session
from sites.base import (
    ChangePreview,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "vagas"


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    (see the module docstring) -- currently just checks that navigating to
    the login page itself doesn't stay there, which is weak on its own but
    consistent with never guessing a "logged in" selector ahead of time."""
    from config import VAGAS_LOGIN_URL

    page = context.new_page()
    try:
        page.goto(VAGAS_LOGIN_URL)
        page.wait_for_load_state("networkidle")
        return "login-candidatos" not in page.url
    finally:
        page.close()


class VagasAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        if not session.has_saved_session(self.site_name):
            return SessionStatus.NOT_LOGGED_IN

        from config import SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
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
        manual step the CLI's `vagas-login` command calls. Returns whether
        the session actually verified as authenticated afterward."""
        from config import VAGAS_LOGIN_URL

        return session.login_interactively(self.site_name, VAGAS_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(
            "Ainda não implementado -- o profile edit page real (URL e seletores) precisa "
            "ser inspecionado numa sessão autenticada de verdade primeiro. Rode "
            "`python src/cli.py vagas-login` e me avise para eu inspecionar a página."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError("Ainda não implementado -- ver inspect_current_profile().")
