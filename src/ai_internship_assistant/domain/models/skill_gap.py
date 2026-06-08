"""Stable models for deterministic candidate/job skill-gap analysis."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.analysis import RequirementLevel


class MatchType(StrEnum):
    """Strength of evidence connecting candidate and job terminology."""

    EXACT = "exact"
    NORMALIZED = "normalized"
    RELATED = "related"
    NONE = "none"


class GapSeverity(StrEnum):
    """Severity of one skill gap or the aggregate report."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConcernSeverity(StrEnum):
    """Severity of a possible job-fit concern."""

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    DISQUALIFYING = "disqualifying"


class SkillMatch(BaseModel):
    """Evidence-backed direct or normalized candidate/job skill match."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    candidate_evidence: str = Field(min_length=1)
    job_evidence: str = Field(min_length=1)
    match_type: MatchType
    confidence: float = Field(ge=0.0, le=1.0)


class SkillGap(BaseModel):
    """One job skill not directly supported by the candidate profile."""

    model_config = ConfigDict(extra="forbid")

    skill_name: str = Field(min_length=1)
    requirement_level: RequirementLevel
    job_evidence: str = Field(min_length=1)
    gap_severity: GapSeverity
    recommendation: str = Field(min_length=1)
    safe_to_add_to_resume: bool = False


class CertificationGap(BaseModel):
    """Certification requested by a job but absent from the candidate profile."""

    model_config = ConfigDict(extra="forbid")

    certification_name: str = Field(min_length=1)
    requirement_level: RequirementLevel
    candidate_has_certification: bool
    gap_severity: GapSeverity
    recommendation: str = Field(min_length=1)


class DisqualifyingConcern(BaseModel):
    """Possible job-fit concern that still requires user judgment."""

    model_config = ConfigDict(extra="forbid")

    concern_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    evidence: str = Field(min_length=1)
    severity: ConcernSeverity


class ResumeEmphasisOpportunity(BaseModel):
    """Safe opportunity to emphasize existing evidence for a related keyword."""

    model_config = ConfigDict(extra="forbid")

    existing_candidate_skill: str = Field(min_length=1)
    related_job_keyword: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    safe_resume_strategy: str = Field(min_length=1)


class SkillGapReport(BaseModel):
    """Independent comparison result for one candidate profile and job analysis."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    candidate_name: str | None = None
    matched_required_skills: list[SkillMatch] = Field(default_factory=list)
    matched_preferred_skills: list[SkillMatch] = Field(default_factory=list)
    missing_required_skills: list[SkillGap] = Field(default_factory=list)
    missing_preferred_skills: list[SkillGap] = Field(default_factory=list)
    matched_certifications: list[SkillMatch] = Field(default_factory=list)
    missing_certifications: list[CertificationGap] = Field(default_factory=list)
    disqualifying_concerns: list[DisqualifyingConcern] = Field(default_factory=list)
    resume_emphasis_opportunities: list[ResumeEmphasisOpportunity] = Field(default_factory=list)
    learning_recommendations: list[str] = Field(default_factory=list)
    overall_gap_severity: GapSeverity
    match_summary: str = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
