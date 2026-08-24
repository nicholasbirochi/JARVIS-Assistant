"""Orchestrates a real job search across the site adapters solid enough
for an unattended, JARVIS-triggered run (InfoJobs, Catho, Gupy).

Indeed is excluded here because of its active IP block (see
sites/indeed.py's module docstring -- repeated automated searches
got this machine 403'd) and LinkedIn because it needs a careful, human-
supervised login and carries the highest anti-automation risk of any
site in this project (see sites/linkedin.py). Both stay reachable
for an explicit, manual request instead of folding them into this
automatic path -- an unattended voice/text tool call is exactly the kind
of unsupervised, repeated use that got Indeed blocked in the first
place.

Bounded on purpose (_MAX_TERMS, _MAX_RESULTS_PER_TERM): this runs
synchronously inside a JARVIS tool call (voice or text), so it can't take
the many minutes a truly exhaustive sweep (every derived term, every
site, deep pagination) would need. For a deeper sweep, call the
adapters' own search_jobs() directly with higher max_results, same as
this project's own development sessions have done.

Results split into "local" (jarvis.sites.job_matching.filter_by_location
-- São Bernardo do Campo/Centro de SP/ABC region, per the user's own
explicit request) and "remote" (filter_remote -- home office, national
or international) -- these are NOT mutually exclusive in principle, but
in practice a listing rarely matches both filters at once (a location-
tagged city and a remote-work phrase together), so no de-duplication
between the two lists is done.

is_daily_search_due()/run_daily_search_if_due() (added 2026-08-12): a
once-a-day automatic refresh, at the user's explicit request. Tracked via
a single timestamp file (data/job_matches/last_run.json), not a real OS
scheduler (cron/launchd) -- this only fires while JARVIS's menu-bar app
is actually running and checks in periodically (see menubar.py),
same real-world limit any local, non-daemonized scheduled task has: if
the Mac is asleep or the app isn't open at all for a whole day, that
day's refresh is simply skipped, not queued up. Real, worth knowing
before relying on it: Catho's adapter hardcodes headless=False (see
catho.py), so a due refresh pops up a real, visible browser window --
this can happen at any point while JARVIS is running, not just at a
convenient moment.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from resume.schema import Resume
from sites.base import JobListing

_MAX_TERMS = 3
_MAX_RESULTS_PER_TERM = 20


@dataclass
class JobSearchReport:
    generated_at: str
    terms: list[str]
    local: list[JobListing] = field(default_factory=list)
    remote: list[JobListing] = field(default_factory=list)
    sites_searched: list[str] = field(default_factory=list)
    sites_failed: dict[str, str] = field(default_factory=dict)


def _default_adapters() -> dict[str, object]:
    from sites.catho import CathoAdapter
    from sites.gupy import GupyAdapter
    from sites.infojobs import InfoJobsAdapter

    return {"infojobs": InfoJobsAdapter(), "catho": CathoAdapter(), "gupy": GupyAdapter()}


def run_job_search(
    resume: Resume,
    *,
    adapters: dict[str, object] | None = None,
    max_terms: int | None = None,
    max_results_per_term: int | None = None,
) -> JobSearchReport:
    """Real, live search -- opens real browser sessions. adapters is
    injectable for tests (fakes, no real Playwright/network calls).

    max_terms/max_results_per_term default to _MAX_TERMS/
    _MAX_RESULTS_PER_TERM (bounded, for the synchronous voice/text tool-
    call path -- see module docstring) but callers with more time to
    spend (job_portal/'s manually-triggered "Atualizar vagas
    agora", not something that fires unattended) can pass higher values,
    or max_terms=0 for "every term in derive_search_terms(resume), no
    slicing" -- added 2026-08-14 after the portal's own quick default
    undersold real coverage once Nicholas set 7 explicit target_roles."""
    from sites.job_matching import (
        dedupe,
        derive_search_terms,
        filter_by_location,
        filter_relevant,
        filter_remote,
        rank_bank_bigtech_first,
        rank_junior_first,
    )

    adapters = adapters if adapters is not None else _default_adapters()
    all_terms = derive_search_terms(resume)
    if max_terms is None:
        max_terms = _MAX_TERMS
    terms = all_terms if max_terms == 0 else all_terms[:max_terms]
    results_cap = max_results_per_term if max_results_per_term is not None else _MAX_RESULTS_PER_TERM

    all_listings: list[JobListing] = []
    sites_searched = []
    sites_failed: dict[str, str] = {}
    for site_name, adapter in adapters.items():
        site_ok = False
        for term in terms:
            try:
                results = adapter.search_jobs(term, max_results=results_cap)
                all_listings.extend(results)
                site_ok = True
            except Exception as exc:  # noqa: BLE001 -- one bad site must not sink the whole search
                sites_failed[site_name] = str(exc)
        if site_ok:
            sites_searched.append(site_name)

    deduped = dedupe(all_listings)
    relevant = filter_relevant(deduped, terms)

    # rank_bank_bigtech_first runs first (inner), rank_junior_first last
    # (outer) -- sorted() is stable, so this makes junior-fit the primary
    # key and known-employer the tiebreaker within each junior tier,
    # rather than the other way around: a role realistically at his level
    # matters more than which company it's at.
    local = rank_junior_first(rank_bank_bigtech_first(filter_by_location(relevant)))
    remote = rank_junior_first(rank_bank_bigtech_first(filter_remote(relevant)))

    return JobSearchReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        terms=terms,
        local=local,
        remote=remote,
        sites_searched=sites_searched,
        sites_failed=sites_failed,
    )


def _reports_dir() -> Path:
    from config import DATA_DIR

    return DATA_DIR / "job_matches"


def save_report(report: JobSearchReport) -> str:
    """Writes a full Markdown report to disk (data/job_matches/, tracked
    like the rest of data/ -- no PII in a JobListing, just public listing
    text). Returns the path as a string."""
    out_dir = _reports_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report.generated_at.replace(":", "").replace("-", "").split(".")[0]
    path = out_dir / f"vagas_{stamp}.md"
    path.write_text(_render_markdown(report), encoding="utf-8")
    return str(path)


def latest_report_path() -> Path | None:
    """Most recently saved report, or None if a search has never been run."""
    out_dir = _reports_dir()
    if not out_dir.exists():
        return None
    candidates = sorted(out_dir.glob("vagas_*.md"))
    return candidates[-1] if candidates else None


def _render_markdown(report: JobSearchReport) -> str:
    lines = [
        f"# Vagas encontradas -- {report.generated_at}",
        "",
        f"Termos buscados: {', '.join(report.terms)}",
        f"Sites pesquisados: {', '.join(report.sites_searched) or 'nenhum'}",
    ]
    if report.sites_failed:
        lines.append(f"Sites que falharam: {', '.join(report.sites_failed)}")
    lines.append("")
    lines.append(f"## Presencial/híbrido perto de você ({len(report.local)})")
    lines.append("")
    lines.extend(_render_listing_lines(report.local))
    lines.append("")
    lines.append(f"## Home office -- nacional e internacional ({len(report.remote)})")
    lines.append("")
    lines.extend(_render_listing_lines(report.remote))
    return "\n".join(lines)


def _render_listing_lines(listings: list[JobListing]) -> list[str]:
    from sites.job_matching import company_tier

    if not listings:
        return ["_Nenhuma vaga encontrada nesta categoria._"]
    lines = []
    for listing in listings:
        tier = company_tier(listing.company)
        tag = {"banco": " 🏦", "fintech": " 💳", "bigtech": " 💻"}.get(tier, "")
        lines.append(
            f"- **{listing.title}**{tag} -- {listing.company or 'empresa não identificada'} -- "
            f"{listing.location or 'localização não informada'} -- [{listing.site_name}]({listing.url})"
        )
    return lines


def summarize(report: JobSearchReport, saved_path: str, *, top_n: int = 5) -> str:
    """Short text summary meant for a voice/text reply -- NOT the full
    list, which can easily run to dozens of items and would be unusable
    read aloud. The full list lives in saved_path."""
    parts = [f"Busquei em: {', '.join(report.sites_searched) or 'nenhum site -- todos falharam'}."]
    if report.sites_failed:
        parts.append(f"Não consegui buscar em: {', '.join(report.sites_failed)}.")
    parts.append(f"{len(report.local)} vagas presenciais/híbridas perto de você, {len(report.remote)} home office.")

    if report.local:
        parts.append("Destaques perto de você:")
        parts.extend(
            f"- {listing.title} ({listing.company or '?'}, {listing.location}): {listing.url}"
            for listing in report.local[:top_n]
        )
    if report.remote:
        parts.append("Destaques home office:")
        parts.extend(
            f"- {listing.title} ({listing.company or '?'}): {listing.url}" for listing in report.remote[:top_n]
        )
    parts.append(f"Lista completa salva em {saved_path}.")
    return "\n".join(parts)


def _last_run_path() -> Path:
    return _reports_dir() / "last_run.json"


def _read_last_run() -> datetime | None:
    path = _last_run_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return datetime.fromisoformat(data["last_run"])
    except Exception:
        return None


def _write_last_run(when: datetime) -> None:
    path = _last_run_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_run": when.isoformat()}), encoding="utf-8")


def is_daily_search_due(*, now: datetime | None = None) -> bool:
    """True if a search has never run, or the last one was 24h+ ago."""
    now = now or datetime.now(timezone.utc)
    last_run = _read_last_run()
    if last_run is None:
        return True
    return (now - last_run) >= timedelta(hours=24)


def run_daily_search_if_due(
    resume: Resume, *, adapters: dict[str, object] | None = None, now: datetime | None = None
) -> JobSearchReport | None:
    """Runs and saves a real search only if is_daily_search_due() -- None
    otherwise, so a caller polling this often (e.g. every hour while
    JARVIS is running, see menubar.py) doesn't re-search needlessly.
    Updates the "last run" timestamp regardless of whether any site
    actually succeeded -- a site being temporarily down shouldn't make
    this retry every poll for the rest of the day."""
    now = now or datetime.now(timezone.utc)
    if not is_daily_search_due(now=now):
        return None
    report = run_job_search(resume, adapters=adapters)
    save_report(report)
    _write_last_run(now)
    return report
