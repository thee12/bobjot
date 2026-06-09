"""Typed immutable artifact models returned by the persistence layer."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.analysis import JobAnalysis
from ai_internship_assistant.domain.models.ats_match import ATSMatchReport
from ai_internship_assistant.domain.models.full_resume_optimization import (
    OptimizedResume,
    ResumeChange,
    ResumeOptimizationSafetyReport,
)
from ai_internship_assistant.domain.models.job import JobPosting
from ai_internship_assistant.domain.models.resume import Resume
from ai_internship_assistant.domain.models.resume_optimization import (
    ExpectedScoreImprovement,
    PlanPriority,
    ResumeOptimizationPlan,
)
from ai_internship_assistant.domain.models.skill_gap import SkillGapReport


class ResumeType(StrEnum):
    """Kinds of structured resume artifacts stored by the application."""

    MASTER = "master"
    OPTIMIZED = "optimized"
    IMPORTED = "imported"
    GENERATED = "generated"


class ResumeSourceFileMetadata(BaseModel):
    """Non-binary metadata retained for an uploaded resume source file."""

    model_config = ConfigDict(extra="forbid")

    original_filename: str = Field(min_length=1)
    file_type: str = Field(min_length=1)
    file_size_bytes: int = Field(ge=0)
    uploaded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    content_hash: str = Field(min_length=1)


class StoredResume(BaseModel):
    """Typed master resume record reconstructed from persistence."""

    model_config = ConfigDict(extra="forbid")

    id: str
    candidate_name: str | None = None
    resume_type: ResumeType
    original_filename: str | None = None
    parsed_resume: Resume
    source_text_hash: str
    source_file_metadata: ResumeSourceFileMetadata | None = None
    created_at: datetime
    updated_at: datetime
    is_master: bool
    model_schema_version: str
    compatibility_warnings: list[str] = Field(default_factory=list)


class StoredResumeVersion(BaseModel):
    """Immutable optimized resume version with its complete audit history."""

    model_config = ConfigDict(extra="forbid")

    id: str
    master_resume_id: str
    version_name: str
    target_job_id: str | None = None
    target_job_title: str | None = None
    target_company: str | None = None
    optimized_resume: OptimizedResume
    optimization_plan: ResumeOptimizationPlan
    skill_gap_report: SkillGapReport
    ats_match_report: ATSMatchReport
    safety_report: ResumeOptimizationSafetyReport
    change_log: list[ResumeChange] = Field(default_factory=list)
    before_ats_score: float = Field(ge=0.0, le=100.0)
    estimated_after_score_low: float = Field(ge=0.0)
    estimated_after_score_high: float = Field(ge=0.0)
    optimization_priority: PlanPriority
    optimized_content_hash: str
    created_at: datetime
    optimizer_version: str
    notes: list[str] = Field(default_factory=list)
    model_schema_version: str
    compatibility_warnings: list[str] = Field(default_factory=list)


class ResumeVersionSummary(BaseModel):
    """Lightweight resume-version projection for list views."""

    model_config = ConfigDict(extra="forbid")

    id: str
    version_name: str
    target_job_title: str | None = None
    target_company: str | None = None
    before_ats_score: float = Field(ge=0.0, le=100.0)
    estimated_after_score_low: float = Field(ge=0.0)
    estimated_after_score_high: float = Field(ge=0.0)
    optimization_priority: PlanPriority
    created_at: datetime


class StoredJob(BaseModel):
    """Minimal persisted job artifact linked to future resume versions."""

    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    company: str
    location: str | None = None
    source: str
    source_url: str | None = None
    apply_url: str | None = None
    job_posting: JobPosting
    job_analysis: JobAnalysis | None = None
    discovered_at: datetime
    created_at: datetime
    model_schema_version: str
    compatibility_warnings: list[str] = Field(default_factory=list)


class ResumeVersionComparison(BaseModel):
    """Minimal comparison contract for future visual diff tooling."""

    model_config = ConfigDict(extra="forbid")

    version_a: ResumeVersionSummary
    version_b: ResumeVersionSummary
    score_estimate_delta_low: float
    score_estimate_delta_high: float
    change_type_counts_a: dict[str, int] = Field(default_factory=dict)
    change_type_counts_b: dict[str, int] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ResumeVersionCreationContext(BaseModel):
    """Complete persistence input retained separately from optimizer execution."""

    model_config = ConfigDict(extra="forbid")

    estimated_after_score: ExpectedScoreImprovement
    optimization_priority: PlanPriority
