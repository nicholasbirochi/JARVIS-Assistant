"""Common interface every job-site adapter will implement (Phase 5+ -- not
implemented yet, this is the interface + supporting types only).

Design decisions, settled now so every future adapter follows the same
contract:

- Login is always a one-time MANUAL step in a real browser window. Playwright
  persists the authenticated session afterwards via `storage_state`/a
  per-site user-data-dir. No password ever passes through this app's code --
  "never store site passwords in plaintext" is satisfied by construction
  (there's no password to store), not by encrypting one.
- `apply_changes` is the ONLY method allowed to mutate anything on the real
  site, and it refuses unless called with `confirmed=True` -- set only after
  a human has seen `preview_changes()`'s output. Dry-run first, always.
- If a site demands MFA/CAPTCHA/any additional verification, the adapter
  must surface that as a SessionStatus (not attempt to solve or bypass it)
  and hand control back to the user.
- Never claim full support for a site until its real flows have actually
  been tested end-to-end against that site.

Recommendation for the first real adapter: Gupy, not LinkedIn.
LinkedIn has aggressive, well-documented anti-automation infrastructure
(behavioral/device fingerprinting, rate limiting, CAPTCHA, and explicit ToS
language against automating profile edits) -- real account-restriction risk
that's disproportionate to automating a few infrequent field edits on one
personal account. Gupy is a Brazilian candidate-facing ATS built around an
editable candidate profile as a first-class, expected user action -- closer
to routine form CRUD than an adversarial target. This is a reasoned relative
judgment, not a verified fact -- validate empirically with a slow, low-volume,
human-paced session against the real account before investing real
engineering time. If LinkedIn is ever revisited, restrict it to
`check_session`/`preview_changes` only -- never wire `apply_changes` for it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from jarvis.resume.schema import Resume


class SessionStatus(str, Enum):
    AUTHENTICATED = "authenticated"
    NOT_LOGGED_IN = "not_logged_in"
    REQUIRES_MFA = "requires_mfa"
    REQUIRES_CAPTCHA = "requires_captcha"
    SESSION_EXPIRED = "session_expired"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class SiteProfileSnapshot:
    """Read-only scrape of what the site currently shows -- the "before"
    side of the diff that build_update_plan() compares against."""

    site_name: str
    fields: dict[str, Any] = field(default_factory=dict)
    captured_at: str = ""


@dataclass
class PlannedFieldChange:
    site_field: str
    current_value: Any
    new_value: Any
    resume_field_path: str


@dataclass
class UpdatePlan:
    site_name: str
    changes: list[PlannedFieldChange] = field(default_factory=list)


@dataclass
class ChangePreview:
    """Rendered diff for human review -- produced by preview_changes(),
    never submits anything. This is the "dry run" the user must see before
    apply_changes() can be called with confirmed=True."""

    site_name: str
    plan: UpdatePlan
    summary_text: str


@dataclass
class UpdateResult:
    site_name: str
    applied: bool
    changes_applied: list[PlannedFieldChange] = field(default_factory=list)
    error: str | None = None
    evidence_path: str | None = None  # screenshot/log captured for the audit trail


@dataclass
class JobListing:
    """One search result from a site's own job search -- read-only, no
    relation to the candidate-profile types above. site_name + external_id
    together are the natural dedupe key across repeated searches; url is
    always absolute (adapters must resolve any site-relative href before
    constructing this)."""

    site_name: str
    external_id: str
    title: str
    company: str | None
    location: str | None
    url: str
    snippet: str | None = None
    salary: str | None = None


class SiteAdapter(ABC):
    """One adapter per job site. Implementations live in
    jarvis/sites/<site_name>.py (e.g. jarvis/sites/gupy.py), each backed by
    Playwright with its own persistent, isolated browser profile."""

    site_name: str

    @abstractmethod
    def check_session(self) -> SessionStatus:
        """Verifies the persisted, authenticated browser context is still
        valid. Never attempts to log in itself -- that's always a manual,
        one-time step performed by the user in a real browser window."""

    @abstractmethod
    def inspect_current_profile(self) -> SiteProfileSnapshot:
        """Read-only: scrapes what the site currently shows. No writes."""

    @abstractmethod
    def build_update_plan(self, resume: Resume, current: SiteProfileSnapshot) -> UpdatePlan:
        """Maps the canonical résumé's fields onto this site's own field
        names/edit UI. Site-specific field-mapping logic lives entirely
        here -- the canonical Resume schema stays site-agnostic."""

    @abstractmethod
    def preview_changes(self, plan: UpdatePlan) -> ChangePreview:
        """Dry run: renders the diff for human review. Submits nothing."""

    @abstractmethod
    def apply_changes(self, plan: UpdatePlan, confirmed: bool) -> UpdateResult:
        """The only method allowed to mutate site state. Must refuse
        (return applied=False, error set) unless confirmed=True, which the
        caller sets only after the user has explicitly approved the output
        of preview_changes(). Implementations should capture a screenshot
        or log entry as evidence of success/failure for the audit trail."""
