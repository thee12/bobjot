"""Structured resume models.

These models represent facts parsed from the user's master resume. Future AI
components must treat these facts as the source of truth and must not invent
new experience, dates, credentials, tools, employers, projects, or metrics.
"""

from pydantic import BaseModel, Field

from ai_internship_assistant.domain.models.common import SourceFile


class ResumeSkill(BaseModel):
    """A skill, tool, language, framework, or technology found in the resume."""

    name: str = Field(description="Skill or technology name as supported by the resume.")
    category: str | None = Field(default=None, description="Optional grouping such as language or tool.")


class Education(BaseModel):
    """Education entry from the source resume."""

    institution: str
    program: str | None = None
    degree: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    details: list[str] = Field(default_factory=list)


class Experience(BaseModel):
    """Work, internship, research, volunteer, or leadership experience."""

    organization: str
    title: str
    start_date: str | None = None
    end_date: str | None = None
    location: str | None = None
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)


class Project(BaseModel):
    """Project explicitly present in the resume."""

    name: str
    description: str | None = None
    bullets: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)


class Certification(BaseModel):
    """Certification or credential explicitly present in the resume."""

    name: str
    issuer: str | None = None
    issued_date: str | None = None
    expiration_date: str | None = None


class Resume(BaseModel):
    """Structured representation of a user's master resume."""

    source_file: SourceFile | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    links: list[str] = Field(default_factory=list)
    summary: str | None = None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[ResumeSkill] = Field(default_factory=list)

