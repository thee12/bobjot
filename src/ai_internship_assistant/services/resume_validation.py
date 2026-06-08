"""Validation warnings for structured resume extraction results.

The validator reports extraction quality issues without mutating or rejecting
the Resume object. This keeps parser output usable while making missing or
malformed data visible to callers.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urlparse

from ai_internship_assistant.domain.models import Resume

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ResumeValidationWarningCode(StrEnum):
    """Stable warning identifiers emitted by resume validation."""

    MISSING_NAME = "missing_name"
    MISSING_EDUCATION = "missing_education"
    NO_TECHNICAL_SKILLS = "no_technical_skills"
    DUPLICATE_SKILL = "duplicate_skill"
    MALFORMED_EMAIL = "malformed_email"
    MALFORMED_URL = "malformed_url"


@dataclass(frozen=True, slots=True)
class ResumeValidationWarning:
    """A non-blocking warning about parsed resume quality."""

    code: ResumeValidationWarningCode
    message: str
    field: str | None = None
    value: str | None = None


class ResumeValidator:
    """Validate extracted Resume objects and return non-blocking warnings."""

    _TECHNICAL_SKILL_CATEGORIES = {
        "technical",
        "technical skill",
        "technical skills",
        "programming language",
        "programming languages",
        "language",
        "languages",
        "framework",
        "frameworks",
        "tool",
        "tools",
        "technology",
        "technologies",
        "database",
        "databases",
    }

    def validate(self, resume: Resume) -> list[ResumeValidationWarning]:
        """Return validation warnings for a structured resume."""

        warnings: list[ResumeValidationWarning] = []
        warnings.extend(self._validate_required_sections(resume))
        warnings.extend(self._validate_skills(resume))
        warnings.extend(self._validate_email(resume))
        warnings.extend(self._validate_urls(resume))
        return warnings

    def _validate_required_sections(self, resume: Resume) -> list[ResumeValidationWarning]:
        warnings: list[ResumeValidationWarning] = []

        if resume.full_name is None:
            warnings.append(
                ResumeValidationWarning(
                    code=ResumeValidationWarningCode.MISSING_NAME,
                    message="Resume is missing a candidate name.",
                    field="full_name",
                )
            )
        if not resume.education:
            warnings.append(
                ResumeValidationWarning(
                    code=ResumeValidationWarningCode.MISSING_EDUCATION,
                    message="Resume does not include any education entries.",
                    field="education",
                )
            )

        return warnings

    def _validate_skills(self, resume: Resume) -> list[ResumeValidationWarning]:
        warnings: list[ResumeValidationWarning] = []
        normalized_skills: set[str] = set()
        duplicate_skills: set[str] = set()
        has_technical_skill = False

        for skill in resume.skills:
            normalized_name = skill.name.casefold()
            if normalized_name in normalized_skills:
                duplicate_skills.add(skill.name)
            normalized_skills.add(normalized_name)

            category = skill.category.casefold() if skill.category is not None else ""
            if category in self._TECHNICAL_SKILL_CATEGORIES:
                has_technical_skill = True

        if resume.skills and not has_technical_skill:
            has_technical_skill = True

        if not has_technical_skill:
            warnings.append(
                ResumeValidationWarning(
                    code=ResumeValidationWarningCode.NO_TECHNICAL_SKILLS,
                    message="Resume does not include any detected technical skills.",
                    field="skills",
                )
            )

        for duplicate in sorted(duplicate_skills, key=str.casefold):
            warnings.append(
                ResumeValidationWarning(
                    code=ResumeValidationWarningCode.DUPLICATE_SKILL,
                    message=f"Duplicate skill detected: {duplicate}",
                    field="skills",
                    value=duplicate,
                )
            )

        return warnings

    def _validate_email(self, resume: Resume) -> list[ResumeValidationWarning]:
        if resume.email is None or _EMAIL_PATTERN.fullmatch(resume.email) is not None:
            return []

        return [
            ResumeValidationWarning(
                code=ResumeValidationWarningCode.MALFORMED_EMAIL,
                message="Resume email appears malformed.",
                field="email",
                value=resume.email,
            )
        ]

    def _validate_urls(self, resume: Resume) -> list[ResumeValidationWarning]:
        warnings: list[ResumeValidationWarning] = []
        url_fields: dict[str, Sequence[str | None]] = {
            "linkedin_url": [resume.linkedin_url],
            "github_url": [resume.github_url],
            "links": resume.links,
        }

        for field, values in url_fields.items():
            for value in values:
                if value is not None and not self._is_valid_url(value):
                    warnings.append(
                        ResumeValidationWarning(
                            code=ResumeValidationWarningCode.MALFORMED_URL,
                            message=f"Resume URL appears malformed in {field}.",
                            field=field,
                            value=value,
                        )
                    )

        return warnings

    def _is_valid_url(self, value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
