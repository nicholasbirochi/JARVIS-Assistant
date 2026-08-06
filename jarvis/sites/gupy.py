"""First real SiteAdapter implementation -- see jarvis/sites/base.py for why
Gupy was picked first (not LinkedIn) and the hard rules every adapter here
follows (manual login only, apply_changes refuses without confirmed=True,
dry-run always comes first).

Two things are already verified against the real, live site (not guessed):
- Domain/URLs: login.gupy.io/candidates/signin, portal.gupy.io -- confirmed
  by fetching Gupy's own public pages.
- check_session()'s logic: after loading a saved session, staying on
  portal.gupy.io means authenticated; landing back on login.gupy.io means
  the session expired.

Two things are NOT yet verified, on purpose, rather than guessed:
- _scrape_profile_fields(): the actual DOM of the logged-in candidate
  profile/résumé edit page. Raises NotImplementedError until this has
  actually been inspected against a live, logged-in session -- shipping
  fabricated CSS selectors that were never seen to work would silently
  produce wrong data, which is worse than admitting the gap.
- The "click submit" half of apply_changes() -- same reasoning.

_map_resume_to_gupy_fields() and build_update_plan()/preview_changes() are
real, tested logic already -- only the scrape/submit boundary is pending.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from jarvis.resume.schema import Resume
from jarvis.sites import session
from jarvis.sites.base import (
    ChangePreview,
    PlannedFieldChange,
    SessionStatus,
    SiteAdapter,
    SiteProfileSnapshot,
    UpdatePlan,
    UpdateResult,
)

SITE_NAME = "gupy"


def _map_resume_to_gupy_fields(resume: Resume) -> dict[str, Any]:
    """Canonical résumé -> Gupy's own field names. Only the fields a
    candidate profile on a Brazilian ATS conventionally exposes for direct
    editing (name/contact/summary) are mapped for now -- experience/
    education/certifications on Gupy are usually structured sub-forms (add
    one entry at a time) rather than flat fields, and mapping those needs
    the same live-DOM verification as _scrape_profile_fields(); left out
    rather than guessed."""
    return {
        "full_name": resume.personal_info.full_name,
        "phone": resume.personal_info.phone,
        "email": resume.personal_info.email,
        "summary": resume.summary.pt,
    }


class GupyAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        if not session.has_saved_session(self.site_name):
            return SessionStatus.NOT_LOGGED_IN

        from jarvis.config import GUPY_LOGIN_URL, GUPY_PORTAL_URL, SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(GUPY_PORTAL_URL)
            page.wait_for_load_state("networkidle")
            if "login.gupy.io" in page.url:
                return SessionStatus.SESSION_EXPIRED
            # portal.gupy.io itself is a public page and does NOT force-redirect
            # an anonymous visitor to the login page (verified live) -- the
            # real signal is whether it's still showing the "Entrar" link
            # that points at the login page, vs. an authenticated account
            # area. A URL-only check silently reported AUTHENTICATED even
            # for a session with no real auth cookie in it (caught live).
            login_link = page.query_selector(f'a[href="{GUPY_LOGIN_URL}"]')
            if login_link is not None:
                return SessionStatus.SESSION_EXPIRED
            return SessionStatus.AUTHENTICATED
        except Exception:
            return SessionStatus.UNKNOWN_ERROR
        finally:
            context.close()
            p.stop()

    def login(self) -> None:
        """Not part of the SiteAdapter interface (check_session() never logs
        in itself, by design) -- this is the explicit, separate, one-time
        manual step the CLI's `gupy-login` command calls."""
        from jarvis.config import GUPY_LOGIN_URL

        session.login_interactively(self.site_name, GUPY_LOGIN_URL)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        from jarvis.config import GUPY_PORTAL_URL, SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(GUPY_PORTAL_URL)
            fields = self._scrape_profile_fields(page)
        finally:
            context.close()
            p.stop()
        return SiteProfileSnapshot(
            site_name=self.site_name,
            fields=fields,
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def _scrape_profile_fields(self, page) -> dict[str, Any]:
        raise NotImplementedError(
            "Selectors da página de perfil da Gupy ainda não foram verificados contra o "
            "site real. Rode `python -m jarvis gupy-login` e faça login; o próximo passo "
            "é inspecionar a página de perfil autenticada e preencher esta função com os "
            "seletores reais antes de usar inspect_current_profile/apply_changes de verdade."
        )

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        desired = _map_resume_to_gupy_fields(resume)
        resume_field_paths = {
            "full_name": "personal_info.full_name",
            "phone": "personal_info.phone",
            "email": "personal_info.email",
            "summary": "summary.pt",
        }
        changes = [
            PlannedFieldChange(
                site_field=field_name,
                current_value=current.fields.get(field_name),
                new_value=new_value,
                resume_field_path=resume_field_paths[field_name],
            )
            for field_name, new_value in desired.items()
            if new_value is not None and current.fields.get(field_name) != new_value
        ]
        return UpdatePlan(site_name=self.site_name, changes=changes)

    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        if not plan.changes:
            summary = "Nenhuma mudança -- o perfil na Gupy já bate com o currículo local."
        else:
            lines = [
                f"- {c.site_field}: {c.current_value!r} -> {c.new_value!r} "
                f"(origem: {c.resume_field_path})"
                for c in plan.changes
            ]
            summary = f"{len(plan.changes)} mudança(s) propostas para {plan.site_name}:\n" + "\n".join(
                lines
            )
        return ChangePreview(site_name=self.site_name, plan=plan, summary_text=summary)

    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        if not confirmed:
            return UpdateResult(
                site_name=self.site_name,
                applied=False,
                error="Recusado: apply_changes exige confirmed=True, só depois de "
                "preview_changes() ter sido mostrado a um humano.",
            )
        if not plan.changes:
            return UpdateResult(site_name=self.site_name, applied=True, changes_applied=[])

        raise NotImplementedError(
            "O preenchimento real do formulário da Gupy ainda não foi verificado contra "
            "o site real -- ver _scrape_profile_fields."
        )
