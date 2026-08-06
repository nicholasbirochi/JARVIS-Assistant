"""First real SiteAdapter implementation -- see jarvis/sites/base.py for why
Gupy was picked first (not LinkedIn) and the hard rules every adapter here
follows (manual login only, apply_changes refuses without confirmed=True,
dry-run always comes first).

Verified against the real, live site (not guessed), via an actual logged-in
session:
- Domains/URLs: login.gupy.io/candidates/signin (login), portal.gupy.io
  (public landing + "Meu currículo" experience/skills/diversity form),
  login.gupy.io/candidates/profile (the *contact-info* edit form --
  name/email/phone/CPF/birth date. Confusingly hosted under the "login"
  subdomain, not "portal" -- found by clicking the account menu's "Editar
  perfil" link from a real session, not guessed).
- check_session()'s real signal: portal.gupy.io never redirects an
  anonymous visitor to the login page (it's a public page) -- the actual
  tell is whether its "Entrar" link (pointing at the login URL) is still
  present.
- _scrape_profile_fields()'s selectors (#name, #lastName,
  #input-with-button-email-input, #input-phone-mobileNumber): read directly
  off the live, authenticated profile page's DOM.

Gupy stores first/last name separately (no single "full name" field) and
the phone field holds the local number only (country code is a separate
selector next to it, defaulted to Brazil) -- _map_resume_to_gupy_fields()
and _scrape_profile_fields() both normalize around that so the diff in
build_update_plan() compares like with like instead of flagging a
formatting difference as a real change.

Deliberately NOT done yet: the "click Save" half of apply_changes(). The
scrape path above is read-only and has been run against the real site;
actually submitting a change to a form that also holds CPF and birth date
is a materially bigger risk to get subtly wrong, and doing that needs its
own explicit, live, human-supervised test run -- not bundled into the same
pass as read-only verification. Raises NotImplementedError until that
happens.
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


def _strip_country_code(phone: str | None) -> str | None:
    """Résumé phone numbers are stored as "+55 (11) 95827-5250"; Gupy's
    mobile-number field holds just "(11) 95827-5250" (country code is a
    separate selector, defaulted to Brazil). Strip the prefix so the two
    are compared on equal footing instead of always looking different."""
    if phone is None:
        return None
    return phone.removeprefix("+55").strip()


def _map_resume_to_gupy_fields(resume: Resume) -> dict[str, Any]:
    """Canonical résumé -> Gupy's own field names. Only the contact-info
    fields verified on the real "Editar perfil" page are mapped --
    experience/education/certifications live in a separate, structured
    sub-form ("Meu currículo") not yet inspected; left out rather than
    guessed."""
    return {
        "full_name": resume.personal_info.full_name,
        "phone": _strip_country_code(resume.personal_info.phone),
        "email": resume.personal_info.email,
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
        from jarvis.config import GUPY_PROFILE_URL, SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(GUPY_PROFILE_URL)
            page.wait_for_load_state("networkidle")
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
        first_name = page.input_value("#name")
        last_name = page.input_value("#lastName")
        return {
            "full_name": f"{first_name} {last_name}".strip(),
            "email": page.input_value("#input-with-button-email-input"),
            "phone": page.input_value("#input-phone-mobileNumber"),
        }

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        desired = _map_resume_to_gupy_fields(resume)
        resume_field_paths = {
            "full_name": "personal_info.full_name",
            "phone": "personal_info.phone",
            "email": "personal_info.email",
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
            "O preenchimento real do formulário da Gupy (clicar Salvar) ainda não foi "
            "testado contra o site real -- a leitura (inspect_current_profile) já foi "
            "verificada ao vivo, mas escrever num formulário que também tem CPF e data "
            "de nascimento merece seu próprio teste supervisionado antes de confiar nele."
        )
