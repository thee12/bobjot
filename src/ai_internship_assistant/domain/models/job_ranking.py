"""Explainable deterministic job-fit ranking models."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, SkipValidation, model_validator

from ai_internship_assistant.domain.models.job import JobPosting


class RecommendationLevel(StrEnum):
    """Human-readable recommendation bands for job fit."""

    STRONG_MATCH = "strong_match"
    GOOD_MATCH = "good_match"
    POSSIBLE_MATCH = "possible_match"
    WEAK_MATCH = "weak_match"
    NOT_RECOMMENDED = "not_recommended"


class JobFitScore(BaseModel):
    """Explainable component and overall fit score for one job."""

    model_config = ConfigDict(extra="forbid")

    overall_score: float = Field(ge=0.0, le=100.0)
    role_match_score: float = Field(ge=0.0, le=100.0)
    skill_match_score: float = Field(ge=0.0, le=100.0)
    domain_match_score: float = Field(ge=0.0, le=100.0)
    experience_level_score: float = Field(ge=0.0, le=100.0)
    location_score: float = Field(ge=0.0, le=100.0)
    employment_type_score: float = Field(ge=0.0, le=100.0)
    certification_match_score: float = Field(ge=0.0, le=100.0)
    keyword_match_score: float = Field(ge=0.0, le=100.0)
    missing_skills: list[str] = Field(default_factory=list)
    matched_skills: list[str] = Field(default_factory=list)
    matched_certifications: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    disqualifying_flags: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    explanation: str


class RankedJobResult(BaseModel):
    """One ranked job and its independent fit score."""

    model_config = ConfigDict(extra="forbid")

    job: SkipValidation[JobPosting]
    score: JobFitScore
    rank: int = Field(ge=1)
    recommendation_level: RecommendationLevel


class RankedJobResultSet(BaseModel):
    """Deterministically sorted job-fit results."""

    model_config = ConfigDict(extra="forbid")

    results: list[RankedJobResult] = Field(default_factory=list)
    total_jobs: int = 0
    ranked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    scoring_version: str
    summary: str

    @model_validator(mode="after")
    def populate_total_jobs(self) -> "RankedJobResultSet":
        """Populate the ranked job count."""

        object.__setattr__(self, "total_jobs", len(self.results))
        return self

