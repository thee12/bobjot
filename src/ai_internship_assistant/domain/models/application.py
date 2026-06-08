"""Application tracking models."""

from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl

from ai_internship_assistant.domain.models.analysis import AtsScore
from ai_internship_assistant.domain.models.common import SourceFile


class ApplicationStatus(StrEnum):
    """Lifecycle states for a tracked job application."""

    DISCOVERED = "discovered"
    SAVED = "saved"
    TAILORED = "tailored"
    APPLIED = "applied"
    REJECTED = "rejected"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    ARCHIVED = "archived"


class GeneratedResumeVersion(BaseModel):
    """Metadata for a tailored resume artifact."""

    version_id: str
    job_posting_id: str | None = None
    source_resume_hash: str | None = None
    generated_file: SourceFile | None = None
    ats_score: AtsScore | None = None
    created_at: str | None = Field(default=None, description="ISO timestamp when generated.")


class ApplicationRecord(BaseModel):
    """Persistent record connecting a job posting, generated resume, and status."""

    application_id: str
    job_posting_id: str
    company: str
    title: str
    job_url: HttpUrl | None = None
    status: ApplicationStatus = ApplicationStatus.DISCOVERED
    generated_resume_versions: list[GeneratedResumeVersion] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

