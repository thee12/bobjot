"""Validation report models for parsed resume quality checks."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ValidationSeverity(StrEnum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationCategory(StrEnum):
    """High-level categories for validation issues."""

    CONTACT = "contact"
    EDUCATION = "education"
    EXPERIENCE = "experience"
    PROJECT = "project"
    SKILL = "skill"
    CERTIFICATION = "certification"
    FORMAT = "format"
    GENERAL = "general"


class ValidationIssue(BaseModel):
    """A single non-mutating validation finding for a parsed resume."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    severity: ValidationSeverity
    category: ValidationCategory
    message: str = Field(min_length=1)
    field_name: str | None = None
    suggestion: str | None = None


class ValidationReport(BaseModel):
    """Validation results for a Resume object.

    The report is independent from the Resume and can be consumed by future
    modules such as candidate profile generation, job discovery, ATS scoring,
    and resume optimization without changing the original parsed resume.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    issues: list[ValidationIssue] = Field(default_factory=list)
    warning_count: int = 0
    error_count: int = 0
    info_count: int = 0
    is_valid: bool = True

    @model_validator(mode="after")
    def populate_summary_fields(self) -> "ValidationReport":
        """Populate issue counts from the issue list."""

        warning_count = self._count_by_severity(ValidationSeverity.WARNING)
        error_count = self._count_by_severity(ValidationSeverity.ERROR)
        info_count = self._count_by_severity(ValidationSeverity.INFO)
        object.__setattr__(self, "warning_count", warning_count)
        object.__setattr__(self, "error_count", error_count)
        object.__setattr__(self, "info_count", info_count)
        object.__setattr__(self, "is_valid", error_count == 0)
        return self

    def _count_by_severity(self, severity: ValidationSeverity) -> int:
        return sum(1 for issue in self.issues if issue.severity == severity)
