"""Traceable models for assembling a complete, factual tailored resume."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.analysis import JobAnalysis
from ai_internship_assistant.domain.models.ats_match import ATSMatchReport
from ai_internship_assistant.domain.models.candidate_profile import CandidateProfile
from ai_internship_assistant.domain.models.common import SourceFile
from ai_internship_assistant.domain.models.resume import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
    Skill,
)
from ai_internship_assistant.domain.models.resume_optimization import (
    ExpectedScoreImprovement,
    ResumeOptimizationPlan,
)
from ai_internship_assistant.domain.models.skill_gap import SkillGapReport


class TargetResumeFormat(StrEnum):
    """Intended future rendering format for the structured optimized resume."""

    STRUCTURED = "structured"
    ATS_PLAIN_TEXT = "ats_plain_text"


class ChangeType(StrEnum):
    """Supported factual transformations performed by the optimizer."""

    SECTION_REORDERED = "section_reordered"
    SKILL_REORDERED = "skill_reordered"
    PROJECT_REORDERED = "project_reordered"
    EXPERIENCE_REORDERED = "experience_reordered"
    BULLET_REWRITTEN = "bullet_rewritten"
    BULLET_UNCHANGED = "bullet_unchanged"
    BULLET_REMOVED = "bullet_removed"
    SECTION_TRIMMED = "section_trimmed"
    SUMMARY_ADDED = "summary_added"
    SUMMARY_UPDATED = "summary_updated"


class SafetyStatus(StrEnum):
    """Safety disposition for a requested or completed resume change."""

    SAFE = "safe"
    WARNING = "warning"
    BLOCKED = "blocked"


class OptimizedResumeContact(BaseModel):
    """Contact facts copied unchanged from the original resume."""

    model_config = ConfigDict(extra="forbid")

    source_file: SourceFile | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    linkedin_url: str | None = None
    github_url: str | None = None
    links: list[str] = Field(default_factory=list)


class OptimizedResumeMetadata(BaseModel):
    """Rendering and traceability metadata for a structured optimized resume."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    source_resume_hash: str
    section_order: list[str] = Field(default_factory=list)
    target_format: TargetResumeFormat
    max_pages: int = Field(ge=1, le=5)


class OptimizedResume(BaseModel):
    """Complete structured tailored resume containing source-supported facts only."""

    model_config = ConfigDict(extra="forbid")

    contact: OptimizedResumeContact
    summary: str | None = None
    education: list[Education] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    additional_sections: dict[str, list[str]] = Field(default_factory=dict)
    target_job_title: str
    target_company: str
    metadata: OptimizedResumeMetadata


class ResumeOptimizationOptions(BaseModel):
    """Configurable deterministic boundaries for full-resume assembly."""

    model_config = ConfigDict(extra="forbid")

    max_pages: int = Field(default=1, ge=1, le=5)
    target_format: TargetResumeFormat = TargetResumeFormat.STRUCTURED
    include_summary: bool = False
    max_projects: int = Field(default=3, ge=0, le=20)
    max_experiences: int = Field(default=4, ge=0, le=20)
    max_bullets_per_project: int = Field(default=3, ge=0, le=20)
    max_bullets_per_experience: int = Field(default=4, ge=0, le=20)
    maximum_bullet_length: int = Field(default=240, ge=40, le=1_000)
    preserve_original_order: bool = False
    enable_bullet_rewrites: bool = True
    enable_section_reordering: bool = True
    enable_skill_reordering: bool = True
    strict_mode: bool = True


class ResumeOptimizationRequest(BaseModel):
    """All factual evidence and safety contracts required by the optimizer."""

    model_config = ConfigDict(extra="forbid")

    resume: Resume
    candidate_profile: CandidateProfile
    job_analysis: JobAnalysis
    skill_gap_report: SkillGapReport
    ats_match_report: ATSMatchReport
    optimization_plan: ResumeOptimizationPlan
    options: ResumeOptimizationOptions = Field(default_factory=ResumeOptimizationOptions)


class ResumeChange(BaseModel):
    """One applied, unchanged, trimmed, or blocked optimization decision."""

    model_config = ConfigDict(extra="forbid")

    change_type: ChangeType
    section_name: str
    item_name: str | None = None
    original_value: str | list[str] | None = None
    new_value: str | list[str] | None = None
    reason: str
    evidence: list[str] = Field(default_factory=list)
    safety_status: SafetyStatus


class ResumeOptimizationSafetyReport(BaseModel):
    """Final factuality audit of a complete optimized resume."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    blocked_changes: list[ResumeChange] = Field(default_factory=list)
    unsafe_keywords_detected: list[str] = Field(default_factory=list)
    forbidden_claims_detected: list[str] = Field(default_factory=list)
    invented_technologies_detected: list[str] = Field(default_factory=list)
    invented_metrics_detected: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class OptimizedResumeResult(BaseModel):
    """Complete optimization output with independent audit and provenance."""

    model_config = ConfigDict(extra="forbid")

    original_resume: Resume
    optimized_resume: OptimizedResume
    optimization_plan: ResumeOptimizationPlan
    skill_gap_report: SkillGapReport
    ats_match_report: ATSMatchReport
    changes: list[ResumeChange] = Field(default_factory=list)
    skipped_changes: list[ResumeChange] = Field(default_factory=list)
    safety_report: ResumeOptimizationSafetyReport
    before_ats_score: float = Field(ge=0.0, le=100.0)
    estimated_after_ats_score: ExpectedScoreImprovement
    optimization_plan_id: str
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    optimizer_version: str
