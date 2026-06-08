"""Normalized candidate profile models for downstream application workflows."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.validation import ValidationReport


class ExperienceLevel(StrEnum):
    """Evidence-based candidate experience classifications."""

    STUDENT = "student"
    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    JUNIOR = "junior"
    MID_LEVEL = "mid_level"
    SENIOR = "senior"


class CandidateDomain(StrEnum):
    """Supported career domains inferred from resume evidence."""

    CYBERSECURITY = "Cybersecurity"
    SOFTWARE_ENGINEERING = "Software Engineering"
    DATA_SCIENCE = "Data Science"
    CLOUD_ENGINEERING = "Cloud Engineering"
    NETWORKING = "Networking"
    DEVOPS = "DevOps"
    MACHINE_LEARNING = "Machine Learning"
    IT_SUPPORT = "IT Support"
    SYSTEMS_ADMINISTRATION = "Systems Administration"
    WEB_DEVELOPMENT = "Web Development"
    GENERAL_TECHNOLOGY = "General Technology"


class ProfileValidationStatus(StrEnum):
    """Summary status derived from the resume validation report."""

    CLEAN = "clean"
    HAS_WARNINGS = "has_warnings"
    HAS_ERRORS = "has_errors"


class CandidateProfile(BaseModel):
    """Central normalized representation of a candidate.

    Candidate profiles are intended for job discovery, ranking, ATS scoring,
    skill-gap analysis, resume optimization, and future recommendation systems.
    All factual fields must be derived from the source Resume. Domain and role
    fields are classifications based on that evidence, not invented history.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    candidate_name: str | None = None
    experience_level: ExperienceLevel = ExperienceLevel.STUDENT
    primary_domain: CandidateDomain = CandidateDomain.GENERAL_TECHNOLOGY
    secondary_domains: list[CandidateDomain] = Field(default_factory=list)
    core_skills: list[str] = Field(default_factory=list)
    supporting_skills: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    target_roles: list[str] = Field(default_factory=list)
    industry_keywords: list[str] = Field(default_factory=list)
    search_keywords: list[str] = Field(default_factory=list)
    education_level: str | None = None
    confidence_score: float = Field(ge=0.0, le=1.0)
    profile_summary: str
    validation_status: ProfileValidationStatus
    validation_messages: list[str] = Field(default_factory=list)


class ProfileGenerationResult(BaseModel):
    """Combined output from validation and candidate profile generation."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    profile: CandidateProfile
    validation_report: ValidationReport
