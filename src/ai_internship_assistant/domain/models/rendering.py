"""Typed contracts for deterministic resume rendering and file output."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

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


class DocxRenderOptions(ResumeRenderOptions):
    """ATS-friendly typography, geometry, and length controls for DOCX export."""

    font_name: str = Field(default="Calibri", min_length=1)
    font_size: float = Field(default=10.5, ge=9.0, le=14.0)
    heading_font_size: float = Field(default=11.5, ge=10.0, le=18.0)
    name_font_size: float = Field(default=15.0, ge=12.0, le=24.0)
    margin_top: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_bottom: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_left: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_right: float = Field(default=0.6, ge=0.4, le=1.5)
    line_spacing: float = Field(default=1.0, ge=0.9, le=2.0)
    bullet_indent: float = Field(default=0.375, ge=0.2, le=1.0)
    max_projects: int | None = Field(default=None, ge=0, le=20)
    max_experiences: int | None = Field(default=None, ge=0, le=20)
    compact_spacing: bool = True
    allow_overwrite: bool = False


class PdfRenderOptions(ResumeRenderOptions):
    """ATS-friendly typography, geometry, and length controls for PDF export."""

    font_name: Literal["Helvetica", "Times-Roman", "Courier"] = "Helvetica"
    font_size: float = Field(default=10.5, ge=9.0, le=14.0)
    heading_font_size: float = Field(default=11.5, ge=10.0, le=18.0)
    name_font_size: float = Field(default=15.0, ge=12.0, le=24.0)
    margin_top: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_bottom: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_left: float = Field(default=0.6, ge=0.4, le=1.5)
    margin_right: float = Field(default=0.6, ge=0.4, le=1.5)
    line_spacing: float = Field(default=1.05, ge=0.9, le=2.0)
    bullet_indent: float = Field(default=0.25, ge=0.1, le=1.0)
    max_projects: int | None = Field(default=None, ge=0, le=20)
    max_experiences: int | None = Field(default=None, ge=0, le=20)
    page_size: Literal["Letter", "A4"] = "Letter"
    compact_mode: bool = True
    allow_overwrite: bool = False
    validate_extractable_text: bool = True


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
    """Metadata for one rendered resume artifact written to disk."""

    model_config = ConfigDict(extra="forbid")

    path: str
    format: ResumeOutputFormat
    byte_size: int = Field(ge=0)
    content_hash: str
    rendered_resume: RenderedResume
    page_count: int | None = Field(default=None, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
