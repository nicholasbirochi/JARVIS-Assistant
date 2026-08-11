"""LinkedIn -- read-only job search only. See jarvis/sites/base.py's module
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
"""

from __future__ import annotations

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

SITE_NAME = "linkedin"

_PROFILE_EDITING_OUT_OF_SCOPE = (
    "Edição de perfil no LinkedIn é intencionalmente fora de escopo (não é 'ainda não "
    "implementado') -- ver o docstring de linkedin.py e de jarvis/sites/base.py. Só "
    "busca de vagas (search_jobs) é suportada aqui."
)


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    -- currently just checks that navigating to the login page itself
    doesn't stay there."""
    from jarvis.config import LINKEDIN_LOGIN_URL

    page = context.new_page()
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
        from jarvis.config import LINKEDIN_LOGIN_URL

        return session.login_interactively(self.site_name, LINKEDIN_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        raise NotImplementedError(_PROFILE_EDITING_OUT_OF_SCOPE)
