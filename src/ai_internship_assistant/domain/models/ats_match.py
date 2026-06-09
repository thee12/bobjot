"""Stable models for estimated ATS resume/job match scoring."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.skill_gap import DisqualifyingConcern


class ATSRecommendationLevel(StrEnum):
    """Interpretation bands for the estimated ATS match score."""

    EXCELLENT_MATCH = "excellent_match"
    STRONG_MATCH = "strong_match"
    GOOD_MATCH = "good_match"
    POSSIBLE_MATCH = "possible_match"
    WEAK_MATCH = "weak_match"
    NOT_RECOMMENDED = "not_recommended"


class OptimizationPriority(StrEnum):
    """Expected value of creating a factual tailored resume for a job."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_WORTH_OPTIMIZING = "not_worth_optimizing"


class ATSComponentScores(BaseModel):
    """Explainable component scores and penalty used by the ATS estimate."""

    model_config = ConfigDict(extra="forbid")

    keyword_score: float = Field(ge=0.0, le=100.0)
    required_skill_score: float = Field(ge=0.0, le=100.0)
    preferred_skill_score: float = Field(ge=0.0, le=100.0)
    certification_score: float = Field(ge=0.0, le=100.0)
    role_alignment_score: float = Field(ge=0.0, le=100.0)
    experience_level_score: float = Field(ge=0.0, le=100.0)
    education_score: float = Field(ge=0.0, le=100.0)
    resume_quality_score: float = Field(ge=0.0, le=100.0)
    disqualifier_penalty: float = Field(ge=0.0)


class KeywordCoverage(BaseModel):
    """ATS keyword coverage against factual resume and profile evidence."""

    model_config = ConfigDict(extra="forbid")

    total_keywords: int = Field(ge=0)
    matched_keywords: int = Field(ge=0)
    missing_keywords: int = Field(ge=0)
    coverage_percentage: float = Field(ge=0.0, le=100.0)
    high_value_matched_keywords: list[str] = Field(default_factory=list)
    high_value_missing_keywords: list[str] = Field(default_factory=list)


class ResumeSectionScore(BaseModel):
    """Keyword support and quality signals for one factual resume section."""

    model_config = ConfigDict(extra="forbid")

    section_name: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=100.0)
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    improvement_opportunities: list[str] = Field(default_factory=list)


class ATSMatchReport(BaseModel):
    """Estimated, explainable ATS alignment of the current resume to one job."""

    model_config = ConfigDict(extra="forbid")

    job_id: str = Field(min_length=1)
    candidate_name: str | None = None
    overall_score: float = Field(ge=0.0, le=100.0)
    recommendation_level: ATSRecommendationLevel
    component_scores: ATSComponentScores
    keyword_coverage: KeywordCoverage
    required_skill_coverage: float = Field(ge=0.0, le=100.0)
    preferred_skill_coverage: float = Field(ge=0.0, le=100.0)
    certification_coverage: float = Field(ge=0.0, le=100.0)
    role_alignment_score: float = Field(ge=0.0, le=100.0)
    experience_alignment_score: float = Field(ge=0.0, le=100.0)
    education_alignment_score: float = Field(ge=0.0, le=100.0)
    resume_section_scores: list[ResumeSectionScore] = Field(default_factory=list)
    matched_ats_keywords: list[str] = Field(default_factory=list)
    missing_ats_keywords: list[str] = Field(default_factory=list)
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    missing_preferred_skills: list[str] = Field(default_factory=list)
    matched_certifications: list[str] = Field(default_factory=list)
    missing_certifications: list[str] = Field(default_factory=list)
    disqualifying_concerns: list[DisqualifyingConcern] = Field(default_factory=list)
    optimization_priority: OptimizationPriority
    optimization_guidance: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scoring_version: str
