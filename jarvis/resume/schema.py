"""Pydantic models for the canonical resume — the single source of truth
that the voice assistant reads from and writes to, and that (in later
phases) gets pushed out to job sites.

Design principle for provenance (Evidence/Conflict): the LLM proposes
*values*, a *confidence*, and a supporting *quote*; source_path/source_type/
read_at are always derived mechanically by code from the file being scanned,
never self-reported by the model."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """additionalProperties: false on every generated schema -- required for
    the local model's structured-output json_schema format used by the
    import script and the document indexer."""

    model_config = ConfigDict(extra="forbid")


class Bilingual(StrictModel):
    """Free-text content that already exists in both languages in the
    source résumés (pt is required, en is optional until translated)."""

    pt: str
    en: Optional[str] = None


class Location(StrictModel):
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None


class Links(StrictModel):
    linkedin: Optional[str] = None
    github: Optional[str] = None
    portfolio: Optional[str] = None
    other: list[str] = Field(default_factory=list)


class Evidence(StrictModel):
    """Where a specific fact came from. Attached to individual résumé items
    so conflicting information from different documents can be tracked
    instead of one silently overwriting another."""

    source_path: str
    source_type: Literal["docx", "pdf", "txt", "md", "voice", "manual"]
    read_at: str  # ISO-8601 UTC
    snippet: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review_status: Literal["pending", "confirmed", "rejected"] = "pending"


class Conflict(StrictModel):
    """Two sources disagreed on a fact -- registered for human review,
    never silently resolved by picking one side."""

    id: str
    field_path: str
    existing_value: Any = None
    proposed_value: Any = None
    sources: list[Evidence] = Field(default_factory=list)
    detected_at: str
    status: Literal["open", "resolved_existing", "resolved_proposed", "resolved_manual"] = "open"
    resolution_note: Optional[str] = None


class ChangeRecord(StrictModel):
    """One entry per applied change to the résumé -- the audit trail."""

    timestamp: str
    field_path: str
    old_value: Any = None
    new_value: Any = None
    source: Literal["voice", "import", "manual_review", "proposal_review"]
    note: Optional[str] = None


class PersonalInfo(StrictModel):
    full_name: str
    location: Location = Field(default_factory=Location)
    phone: Optional[str] = None
    email: Optional[str] = None
    links: Links = Field(default_factory=Links)
    evidence: list[Evidence] = Field(default_factory=list)


class SkillCategory(StrictModel):
    category: str
    items: list[str] = Field(default_factory=list)


class Experience(StrictModel):
    id: str
    title: Bilingual
    company: str
    location: Optional[str] = None
    start_date: Optional[str] = None  # "YYYY-MM"
    end_date: Optional[str] = None
    is_current: bool = False
    bullets_pt: list[str] = Field(default_factory=list)
    bullets_en: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class Education(StrictModel):
    degree: Bilingual
    institution: str
    location: Optional[str] = None
    status: Literal["in_progress", "completed"] = "completed"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)


class Project(StrictModel):
    name: Bilingual
    description: Bilingual
    tech: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)


class Certification(StrictModel):
    name: str
    hours: Optional[int] = None
    status: Literal["in_progress", "completed"] = "completed"
    date: Optional[str] = None  # completed date, or expected date if in_progress
    evidence: list[Evidence] = Field(default_factory=list)


class LanguageSkill(StrictModel):
    name: str
    proficiency: Optional[str] = None
    test_score: Optional[str] = None
    evidence: list[Evidence] = Field(default_factory=list)


class Availability(StrictModel):
    """Grouped under JobPreferences, not the root -- availability is a
    job-search preference/constraint, not a resume fact."""

    status: Literal["immediate", "notice_period", "date", "unspecified"] = "unspecified"
    notice_period_days: Optional[int] = None
    available_from: Optional[str] = None
    notes: Optional[str] = None


class JobPreferences(StrictModel):
    target_roles: list[str] = Field(default_factory=list)
    notes: Optional[str] = None
    availability: Availability = Field(default_factory=Availability)


class ResumeMeta(StrictModel):
    schema_version: str = "2.0"
    canonical_language: str = "pt-BR"
    last_updated: Optional[str] = None
    source_documents: list[str] = Field(default_factory=list)


class Resume(StrictModel):
    meta: ResumeMeta = Field(default_factory=ResumeMeta)
    personal_info: PersonalInfo
    summary: Bilingual
    skills: list[SkillCategory] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    languages: list[LanguageSkill] = Field(default_factory=list)
    job_preferences: JobPreferences = Field(default_factory=JobPreferences)
    conflicts: list[Conflict] = Field(default_factory=list)
    change_log: list[ChangeRecord] = Field(default_factory=list)
