"""Orchestrates a real job search across the site adapters solid enough
for an unattended, JARVIS-triggered run (InfoJobs, Catho, Gupy).

Indeed is excluded here because of its active IP block (see
jarvis/sites/indeed.py's module docstring -- repeated automated searches
got this machine 403'd) and LinkedIn because it needs a careful, human-
supervised login and carries the highest anti-automation risk of any
site in this project (see jarvis/sites/linkedin.py). Both stay reachable
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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from jarvis.resume.schema import Resume
from jarvis.sites.base import JobListing

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
    from jarvis.sites.catho import CathoAdapter
    from jarvis.sites.gupy import GupyAdapter
    from jarvis.sites.infojobs import InfoJobsAdapter

    return {"infojobs": InfoJobsAdapter(), "catho": CathoAdapter(), "gupy": GupyAdapter()}


def run_job_search(resume: Resume, *, adapters: dict[str, object] | None = None) -> JobSearchReport:
    """Real, live search -- opens real browser sessions. adapters is
    injectable for tests (fakes, no real Playwright/network calls)."""
    from jarvis.sites.job_matching import (
        dedupe,
        derive_search_terms,
        filter_by_location,
        filter_relevant,
        filter_remote,
        rank_bank_bigtech_first,
        rank_junior_first,
    )

    adapters = adapters if adapters is not None else _default_adapters()
    terms = derive_search_terms(resume)[:_MAX_TERMS]

    all_listings: list[JobListing] = []
    sites_searched = []
    sites_failed: dict[str, str] = {}
    for site_name, adapter in adapters.items():
        site_ok = False
        for term in terms:
            try:
                results = adapter.search_jobs(term, max_results=_MAX_RESULTS_PER_TERM)
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
    from jarvis.config import DATA_DIR

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
    from jarvis.sites.job_matching import company_tier

    if not listings:
        return ["_Nenhuma vaga encontrada nesta categoria._"]
    lines = []
    for listing in listings:
        tier = company_tier(listing.company)
        tag = " 🏦" if tier == "banco" else " 💻" if tier == "bigtech" else ""
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
