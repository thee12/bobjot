"""Typed contracts for deterministic resume rendering and file output."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ResumeOutputFormat(StrEnum):
    """Current and future resume output formats."""

    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    HTML = "html"
    DOCX = "docx"
    PDF = "pdf"


class BulletStyle(StrEnum):
    """Simple Markdown-compatible bullet markers."""

    DASH = "dash"
    ASTERISK = "asterisk"


class HeadingStyle(StrEnum):
    """Supported heading conventions for Markdown output."""

    MARKDOWN_H1 = "markdown_h1"
    MARKDOWN_H2 = "markdown_h2"
    ATS_SIMPLE = "ats_simple"


class ResumeRenderOptions(BaseModel):
    """Deterministic visibility and formatting options for resume rendering."""

    model_config = ConfigDict(extra="forbid")

    include_summary: bool = True
    include_contact: bool = True
    include_education: bool = True
    include_certifications: bool = True
    include_skills: bool = True
    include_projects: bool = True
    include_experience: bool = True
    include_additional_sections: bool = True
    include_metadata_comment: bool = False
    max_bullets_per_project: int | None = Field(default=None, ge=0, le=100)
    max_bullets_per_experience: int | None = Field(default=None, ge=0, le=100)
    section_order: list[str] | None = None
    bullet_style: BulletStyle = BulletStyle.DASH
    heading_style: HeadingStyle = HeadingStyle.MARKDOWN_H1
    strict_ats_format: bool = True
    source_resume_id: str | None = None
    source_version_id: str | None = None


class RenderedResume(BaseModel):
    """In-memory deterministic resume rendering result."""

    model_config = ConfigDict(extra="forbid")

    content: str
    format: ResumeOutputFormat
    candidate_name: str | None = None
    target_job_title: str | None = None
    target_company: str | None = None
    source_resume_id: str | None = None
    source_version_id: str | None = None
    warnings: list[str] = Field(default_factory=list)
    rendered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    renderer_version: str


class RenderedResumeFile(BaseModel):
    """Metadata for one UTF-8 resume rendering written to disk."""

    model_config = ConfigDict(extra="forbid")

    path: str
    format: ResumeOutputFormat
    byte_size: int = Field(ge=0)
    content_hash: str
    rendered_resume: RenderedResume
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
