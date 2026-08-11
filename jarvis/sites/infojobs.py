"""Fourth real SiteAdapter implementation. See jarvis/sites/base.py for
the hard rules every adapter here follows (manual login only,
apply_changes refuses without confirmed=True, dry-run always comes
first).

Login URL found via WebSearch, confirmed reachable live (not guessed) --
see jarvis/config.py's INFOJOBS_LOGIN_URL comment. Best of the sites
tried so far: Playwright reaches it fine in both headless and headed
mode -- no Cloudflare block like Vagas.com, no headless-only 403 like
Catho -- so this adapter uses config.SITES_HEADLESS normally, unlike
catho.py's hardcoded headless=False.

Verified against the real, live site (not guessed), via an actual
logged-in session:
- The curriculum edit form lives at
  https://www.infojobs.com.br/Candidate/CV/insert2.aspx -- reached from
  the summary page's "Editar" link (which has an ambiguous/hidden
  duplicate on the page, so this adapter navigates straight to the URL
  rather than clicking it).
- `wait_until="domcontentloaded"`, not the default "load"/networkidle --
  the summary and edit pages both carry ad banners that keep the network
  busy indefinitely, so waiting for it to go idle just times out.
- Real field selectors, from the live DOM:
  #ctl00_phMasterPage_cPersonalData_txtName (first name),
  #ctl00_phMasterPage_cPersonalData_txtSurname (last name),
  #ctl00_phMasterPage_cPersonalData_txtPhone1Code (area code, digits only,
  e.g. "11"), #ctl00_phMasterPage_cPersonalData_txtPhone1 (number, digits
  only, e.g. "958275250") -- phone is split into two fields, unlike the
  résumé's single formatted string, so _parse_phone() below normalizes
  between the two representations for comparison.
- Save button: `a.js_btSend` ("SALVAR CV") -- an anchor styled as a
  button, no id, distinct from the per-section "SALVAR FORMAÇÃO"/
  "SALVAR EXPERIÊNCIA" buttons elsewhere on the same page.
- Only full_name and phone are wired to real writes (_WRITABLE_FIELDS),
  same reasoning as Gupy: email isn't even on this form (it's the login
  identifier, kept on a separate account-settings page), so there's
  nothing to guess there. CPF and birth date are visible on this same
  page (next to name/phone) but never read or written -- see
  _scrape_profile_fields() and _record_evidence().

**Known limitation, confirmed live on 2026-08-11: the "SALVAR CV" click
does not currently reach the server.** apply_changes() reloads the page
before re-scraping specifically because of this -- an earlier version
re-scraped the same unreloaded DOM and falsely reported success, since
the <input> elements still held whatever page.fill() itself had written,
regardless of whether the site's own save handler ran. With the reload
in place, a real apply attempt now honestly returns applied=False
instead of lying. Investigated but not yet root-caused: the click fires
zero requests to infojobs.com.br (confirmed via Playwright network-event
logging, both with the normal Playwright .click() and a native
element.click() via page.evaluate()); no JS console errors or
page-level exceptions; no window.Page_ClientValidate/__doPostBack
(so it isn't classic ASP.NET WebForms postback validation blocking it,
despite the ctl00$phMasterPage$... field naming); no React/Vue/Angular
globals found; jQuery is present but no delegated handler was found via
jQuery._data on the element itself. The <a class="js_btSend"> sits
inside a single big <form id="aspnetForm"> that likely spans far more
than the personal-data section (the page is >5000px tall, covering
education/experience/skills too) -- a silent validation failure
somewhere else in that same form is one live hypothesis, not yet
confirmed. Until this is resolved, treat apply_changes() for InfoJobs as
correctly SAFE (never reports a false success) but not yet capable of a
real write -- same posture as Vagas.com/Catho before their real save
paths were confirmed.
"""

from __future__ import annotations

import re
from typing import Any

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

SITE_NAME = "infojobs"

_EDIT_URL = "https://www.infojobs.com.br/Candidate/CV/insert2.aspx"

# Only these site_field values have a real, live-verified write path (see
# module docstring). Anything else in a plan makes apply_changes() refuse
# the whole plan rather than silently writing part of it.
_WRITABLE_FIELDS = {"full_name", "phone"}


def _parse_phone(phone: str | None) -> tuple[str, str] | tuple[None, None]:
    """Résumé phone numbers are stored as "+55 (11) 95827-5250"; InfoJobs
    splits area code and number into two separate digits-only fields.
    Verified live: "+55 (11) 95827-5250" -> area code "11", number
    "958275250"."""
    if phone is None:
        return None, None
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("55") and len(digits) >= 12:
        digits = digits[2:]  # strip the country code
    return digits[:2], digits[2:]


def _split_full_name(full_name: str) -> tuple[str, str]:
    """InfoJobs stores first/last name as two separate fields; the résumé
    keeps one combined string. Splits on the first space, same convention
    verified live for Gupy (see gupy.py) -- a name with no space becomes
    an empty last name rather than raising."""
    first, _, rest = full_name.partition(" ")
    return first, rest


def _map_resume_to_infojobs_fields(resume: Resume) -> dict[str, Any]:
    """Canonical résumé -> InfoJobs' own field names. Only the personal-
    data fields verified on the real edit page are mapped -- experience/
    education/skills live in separate sub-forms on the same page, not yet
    inspected; left out rather than guessed."""
    area_code, number = _parse_phone(resume.personal_info.phone)
    return {
        "full_name": resume.personal_info.full_name,
        "phone": f"{area_code} {number}" if area_code else None,
    }


def _is_authenticated(context) -> bool:
    """Placeholder until the real post-login page/signal is confirmed live
    (see the module docstring) -- currently just checks that navigating to
    the login page itself doesn't stay there."""
    from jarvis.config import INFOJOBS_LOGIN_URL

    page = context.new_page()
    try:
        page.goto(INFOJOBS_LOGIN_URL)
        page.wait_for_load_state("networkidle")
        return "Account/Login" not in page.url
    finally:
        page.close()


class InfoJobsAdapter(SiteAdapter):
    site_name = SITE_NAME

    def check_session(self) -> SessionStatus:
        if not session.has_saved_session(self.site_name):
            return SessionStatus.NOT_LOGGED_IN

        from jarvis.config import SITES_HEADLESS

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
        manual step the CLI's `infojobs-login` command calls. Returns
        whether the session actually verified as authenticated afterward."""
        from jarvis.config import INFOJOBS_LOGIN_URL

        return session.login_interactively(self.site_name, INFOJOBS_LOGIN_URL, verify_fn=_is_authenticated)

    def inspect_current_profile(self) -> SiteProfileSnapshot:
        from datetime import datetime, timezone

        from jarvis.config import SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(_EDIT_URL, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)  # the form fields populate slightly after DOMContentLoaded
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
        first_name = page.input_value("#ctl00_phMasterPage_cPersonalData_txtName")
        last_name = page.input_value("#ctl00_phMasterPage_cPersonalData_txtSurname")
        area_code = page.input_value("#ctl00_phMasterPage_cPersonalData_txtPhone1Code")
        number = page.input_value("#ctl00_phMasterPage_cPersonalData_txtPhone1")
        return {
            "full_name": f"{first_name} {last_name}".strip(),
            "phone": f"{area_code} {number}" if area_code or number else "",
        }

    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        from jarvis.sites.base import PlannedFieldChange

        desired = _map_resume_to_infojobs_fields(resume)
        resume_field_paths = {"full_name": "personal_info.full_name", "phone": "personal_info.phone"}
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
            summary = "Nenhuma mudança -- o perfil no InfoJobs já bate com o currículo local."
        else:
            lines = [
                f"- {c.site_field}: {c.current_value!r} -> {c.new_value!r} (origem: {c.resume_field_path})"
                for c in plan.changes
            ]
            summary = f"{len(plan.changes)} mudança(s) propostas para {plan.site_name}:\n" + "\n".join(lines)
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

        unsupported = [c.site_field for c in plan.changes if c.site_field not in _WRITABLE_FIELDS]
        if unsupported:
            raise NotImplementedError(
                f"Envio real ainda não coberto para: {', '.join(unsupported)}. Nome e "
                "telefone já foram inspecionados ao vivo (ver o docstring de infojobs.py)."
            )

        from jarvis.config import SITES_HEADLESS

        p, context = session.open_context(self.site_name, headless=SITES_HEADLESS)
        try:
            page = context.new_page()
            page.goto(_EDIT_URL, timeout=45_000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)

            for change in plan.changes:
                self._fill_field(page, change.site_field, change.new_value)

            save_btn = page.query_selector("a.js_btSend")
            if save_btn is None:
                return UpdateResult(
                    site_name=self.site_name,
                    applied=False,
                    error="Botão Salvar CV não encontrado -- a página pode ter mudado desde "
                    "a última verificação ao vivo.",
                )
            save_btn.click()
            page.wait_for_timeout(3000)

            evidence_path = self._record_evidence(plan)

            # Reload before re-scraping -- otherwise this reads back the same
            # <input> elements we just wrote via page.fill(), which still
            # hold our own in-memory value regardless of whether the site's
            # own save handler actually ran. Confirmed live: the "SALVAR CV"
            # click can silently do nothing server-side (verified via network
            # logging -- zero requests to infojobs.com.br after the click)
            # while the unreloaded DOM still "looks" saved. A real reload
            # forces us to read the server's own truth.
            page.reload(wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(3000)

            fields_after = self._scrape_profile_fields(page)
            failed = [c for c in plan.changes if fields_after.get(c.site_field) != c.new_value]
            if failed:
                return UpdateResult(
                    site_name=self.site_name,
                    applied=False,
                    error="Clicou Salvar CV, mas o perfil não reflete a mudança em: "
                    f"{', '.join(c.site_field for c in failed)} -- confira manualmente.",
                    evidence_path=evidence_path,
                )
            return UpdateResult(
                site_name=self.site_name, applied=True, changes_applied=plan.changes, evidence_path=evidence_path
            )
        finally:
            context.close()
            p.stop()

    def _fill_field(self, page, site_field: str, value: Any) -> None:
        if site_field == "full_name":
            first, last = _split_full_name(value)
            page.fill("#ctl00_phMasterPage_cPersonalData_txtName", first)
            page.fill("#ctl00_phMasterPage_cPersonalData_txtSurname", last)
        elif site_field == "phone":
            area_code, number = value.split(" ", 1)
            page.fill("#ctl00_phMasterPage_cPersonalData_txtPhone1Code", area_code)
            page.fill("#ctl00_phMasterPage_cPersonalData_txtPhone1", number)
        else:  # pragma: no cover -- unreachable, apply_changes filters first
            raise NotImplementedError(f"Campo não suportado para escrita: {site_field!r}")

    def _record_evidence(self, plan: UpdatePlan) -> str | None:
        """Audit-trail record for a real submission -- deliberately a small
        JSON record of what changed (field/old/new/when), NOT a screenshot.
        The profile page also displays CPF and birth date right next to the
        fields we actually write; a full-page screenshot would capture
        those incidentally even though the write itself never touches
        them. Best-effort -- a failed write here shouldn't fail the whole
        apply, the actual site write already happened by this point."""
        import json
        from datetime import datetime, timezone

        from jarvis.config import SITES_EVIDENCE_DIR

        try:
            SITES_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            path = SITES_EVIDENCE_DIR / f"{self.site_name}_{stamp}.json"
            record = {
                "site_name": self.site_name,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "changes": [
                    {
                        "field": c.site_field,
                        "old_value": c.current_value,
                        "new_value": c.new_value,
                        "resume_field_path": c.resume_field_path,
                    }
                    for c in plan.changes
                ],
            }
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return str(path)
        except Exception:
            return None
