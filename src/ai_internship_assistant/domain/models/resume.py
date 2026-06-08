"""Structured resume models.

These models represent facts parsed from the user's master resume. Future AI
components must treat these facts as the source of truth and must not invent
new experience, dates, credentials, tools, employers, projects, or metrics.
"""

import re
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ai_internship_assistant.domain.models.common import SourceFile

type NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
type OptionalCleanStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResumeBaseModel(BaseModel):
    """Base model settings shared by resume domain objects."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Skill(ResumeBaseModel):
    """A skill, tool, language, framework, or technology found in the resume."""

    name: NonEmptyStr = Field(description="Skill or technology name as supported by the resume.")
    category: OptionalCleanStr | None = Field(
        default=None,
        description="Optional grouping such as language, framework, database, or tool.",
    )


ResumeSkill = Skill


class Education(ResumeBaseModel):
    """Education entry from the source resume."""

    institution: NonEmptyStr
    program: OptionalCleanStr | None = None
    degree: OptionalCleanStr | None = None
    start_date: OptionalCleanStr | None = None
    end_date: OptionalCleanStr | None = None
    details: list[NonEmptyStr] = Field(default_factory=list)


class Experience(ResumeBaseModel):
    """Work, internship, research, volunteer, or leadership experience."""

    organization: NonEmptyStr
    title: NonEmptyStr
    start_date: OptionalCleanStr | None = None
    end_date: OptionalCleanStr | None = None
    location: OptionalCleanStr | None = None
    bullets: list[NonEmptyStr] = Field(default_factory=list)
    technologies: list[NonEmptyStr] = Field(default_factory=list)


class Project(ResumeBaseModel):
    """Project explicitly present in the resume."""

    name: NonEmptyStr
    description: OptionalCleanStr | None = None
    bullets: list[NonEmptyStr] = Field(default_factory=list)
    technologies: list[NonEmptyStr] = Field(default_factory=list)
    links: list[NonEmptyStr] = Field(default_factory=list)


class Certification(ResumeBaseModel):
    """Certification or credential explicitly present in the resume."""

    name: NonEmptyStr
    issuer: OptionalCleanStr | None = None
    issued_date: OptionalCleanStr | None = None
    expiration_date: OptionalCleanStr | None = None


class Resume(ResumeBaseModel):
    """Structured representation of a user's master resume."""

    source_file: SourceFile | None = None
    full_name: OptionalCleanStr | None = None
    email: OptionalCleanStr | None = None
    phone: OptionalCleanStr | None = None
    location: OptionalCleanStr | None = None
    links: list[NonEmptyStr] = Field(default_factory=list)
    summary: OptionalCleanStr | None = None
    education: list[Education] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def validate_email(cls, email: str | None) -> str | None:
        """Reject malformed email addresses when contact email is provided."""

        if email is not None and _EMAIL_PATTERN.fullmatch(email) is None:
            msg = "email must be a valid email address"
            raise ValueError(msg)
        return email

    @model_validator(mode="after")
    def require_resume_content(self) -> "Resume":
        """Require at least one meaningful resume field."""

        has_contact = any([self.full_name, self.email, self.phone, self.location, self.links])
        has_sections = any(
            [
                self.summary,
                self.education,
                self.experience,
                self.projects,
                self.certifications,
                self.skills,
            ]
        )
        if not has_contact and not has_sections:
            msg = "resume must contain at least one contact field or resume section"
            raise ValueError(msg)
        return self
