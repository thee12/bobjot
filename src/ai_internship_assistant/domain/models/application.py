"""Typed contracts for saved jobs and application pipeline tracking."""

from datetime import UTC, date, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.analysis import JobAnalysis
from ai_internship_assistant.domain.models.ats_match import ATSMatchReport
from ai_internship_assistant.domain.models.job import JobPosting


class ApplicationStatus(StrEnum):
    """Lifecycle states for a tracked job application."""

    SAVED = "saved"
    PLANNED = "planned"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"
    FOLLOW_UP_NEEDED = "follow_up_needed"
    INTERVIEWING = "interviewing"
    TECHNICAL_INTERVIEW = "technical_interview"
    FINAL_INTERVIEW = "final_interview"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    CLOSED = "closed"


class ApplicationNoteType(StrEnum):
    """Classification for append-only application notes."""

    GENERAL = "general"
    FOLLOW_UP = "follow_up"
    INTERVIEW = "interview"
    REJECTION = "rejection"
    OFFER = "offer"
    REMINDER = "reminder"
    SYSTEM = "system"


class SavedJobStatus(StrEnum):
    """Availability and lifecycle states for saved jobs."""

    ACTIVE = "active"
    EXPIRED = "expired"
    DUPLICATE = "duplicate"
    ARCHIVED = "archived"


class SavedJob(BaseModel):
    """A persisted job snapshot retained independently from an application."""

    model_config = ConfigDict(extra="forbid")

    id: str
    job_posting_id: str
    title: str
    company: str
    location: str | None = None
    source: str
    source_url: str | None = None
    apply_url: str | None = None
    job_posting: JobPosting
    job_analysis: JobAnalysis | None = None
    ats_match_report: ATSMatchReport | None = None
    fit_score: float | None = Field(default=None, ge=0.0, le=100.0)
    ats_score: float | None = Field(default=None, ge=0.0, le=100.0)
    saved_at: datetime
    last_seen_at: datetime
    status: SavedJobStatus = SavedJobStatus.ACTIVE
    is_active: bool = True
    notes: str | None = None


class JobApplication(BaseModel):
    """A tracked application linked to one saved job and optional resume version."""

    model_config = ConfigDict(extra="forbid")

    id: str
    saved_job_id: str
    resume_version_id: str | None = None
    status: ApplicationStatus = ApplicationStatus.PLANNED
    applied_at: datetime | None = None
    follow_up_date: date | None = None
    interview_date: datetime | None = None
    response_received_at: datetime | None = None
    rejected_at: datetime | None = None
    offer_received_at: datetime | None = None
    withdrawn_at: datetime | None = None
    source: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationNote(BaseModel):
    """One append-only note attached to an application."""

    model_config = ConfigDict(extra="forbid")

    id: str
    application_id: str
    note: str = Field(min_length=1)
    note_type: ApplicationNoteType = ApplicationNoteType.GENERAL
    created_at: datetime


class ApplicationStatusHistory(BaseModel):
    """One auditable application status transition."""

    model_config = ConfigDict(extra="forbid")

    id: str
    application_id: str
    old_status: ApplicationStatus | None = None
    new_status: ApplicationStatus
    changed_at: datetime
    note: str | None = None


class ApplicationFilters(BaseModel):
    """Optional filters for lightweight application-list queries."""

    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus | None = None
    company: str | None = None
    role_keyword: str | None = None
    source: str | None = None
    applied_after: datetime | None = None
    applied_before: datetime | None = None
    needs_follow_up: bool | None = None
    has_interview: bool | None = None
    resume_version_id: str | None = None
    as_of_date: date = Field(default_factory=lambda: datetime.now(UTC).date())


class JobApplicationSummary(BaseModel):
    """Lightweight joined projection for future dashboard list views."""

    model_config = ConfigDict(extra="forbid")

    id: str
    saved_job_id: str
    title: str
    company: str
    status: ApplicationStatus
    applied_at: datetime | None = None
    follow_up_date: date | None = None
    resume_version_id: str | None = None
    ats_score: float | None = Field(default=None, ge=0.0, le=100.0)
    fit_score: float | None = Field(default=None, ge=0.0, le=100.0)
    latest_note: str | None = None
    updated_at: datetime
