"""API-specific request and response contracts."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models import (
    ApplicationNote,
    ApplicationNoteType,
    ApplicationStatus,
    ApplicationStatusHistory,
    ATSMatchReport,
    CandidateProfile,
    JobAnalysis,
    JobApplication,
    JobApplicationSummary,
    JobPosting,
    JobSearchPreferences,
    OptimizedResume,
    PipelineExecutionMode,
    PipelineRun,
    PipelineRunResult,
    PipelineRunStatus,
    PipelineStep,
    Resume,
    ResumeChange,
    ResumeOptimizationOptions,
    ResumeOptimizationSafetyReport,
    ResumeVersionSummary,
    SavedJob,
    SavedJobStatus,
    ValidationReport,
)


class HealthResponse(BaseModel):
    status: str = "ok"
    service: str = "job-bot-api"
    version: str = "0.1.0"


class PipelineRunSummary(BaseModel):
    id: str
    resume_id: str
    status: PipelineRunStatus
    current_step: PipelineStep | None = None
    progress_percentage: int
    warning_count: int
    error_count: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    duration_seconds: float | None = None
    execution_mode: PipelineExecutionMode
    cancellation_requested: bool

    @classmethod
    def from_domain(cls, run: PipelineRun) -> "PipelineRunSummary":
        return cls(
            id=run.id,
            resume_id=run.resume_id,
            status=run.status,
            current_step=run.current_step,
            progress_percentage=run.progress_percentage,
            warning_count=len(run.warnings),
            error_count=len(run.errors),
            started_at=run.started_at,
            completed_at=run.completed_at,
            created_at=run.created_at,
            duration_seconds=run.duration_seconds,
            execution_mode=run.execution_mode,
            cancellation_requested=run.cancellation_requested,
        )


class PipelineResultNotReady(BaseModel):
    pipeline_run_id: str
    status: PipelineRunStatus
    ready: bool = False
    errors: list[str] = Field(default_factory=list)


PipelineResultResponse = PipelineRunResult | PipelineResultNotReady


class DependencyHealthResponse(BaseModel):
    status: str
    database: str
    llm_enabled: bool
    export_directory: str
    export_directory_writable: bool


class ResumeUploadResponse(BaseModel):
    resume_id: str
    candidate_name: str | None = None
    validation_warnings: list[str] = Field(default_factory=list)
    candidate_profile_summary: str
    created_at: datetime


class ResumeSummaryResponse(BaseModel):
    resume_id: str
    candidate_name: str | None = None
    original_filename: str | None = None
    created_at: datetime
    updated_at: datetime
    version_count: int


class ResumeDetailResponse(BaseModel):
    resume_id: str
    candidate_name: str | None = None
    parsed_resume: Resume
    candidate_profile: CandidateProfile
    validation_report: ValidationReport
    created_at: datetime


class ResumeVersionDetailResponse(BaseModel):
    version_id: str
    optimized_resume: OptimizedResume
    target_job_id: str | None = None
    target_job_title: str | None = None
    target_company: str | None = None
    before_ats_score: float
    estimated_after_score_low: float
    estimated_after_score_high: float
    change_log: list[ResumeChange]
    safety_report: ResumeOptimizationSafetyReport
    created_at: datetime


class JobSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: str
    preferences: JobSearchPreferences = Field(default_factory=JobSearchPreferences)
    max_results: int = Field(default=20, ge=1, le=100)
    include_rankings: bool = True
    save_results: bool = False


class JobSearchResponse(BaseModel):
    resume_id: str
    query_count: int
    total_jobs_found: int
    total_unique_jobs: int
    ranked_jobs: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PublicJobPosting(BaseModel):
    """Normalized job posting fields safe for ordinary API responses."""

    id: str
    source: str
    source_name: str
    source_url: str | None = None
    apply_url: str | None = None
    canonical_url: str | None = None
    title: str
    company: str
    location: str | None = None
    employment_type: str
    seniority: str
    work_arrangement: str
    description: str | None = None
    responsibilities: list[str]
    requirements: list[str]
    preferred_qualifications: list[str]
    technologies: list[str]
    certifications: list[str]
    salary_min: float | None = None
    salary_max: float | None = None
    posted_date: date | None = None

    @classmethod
    def from_domain(cls, job: JobPosting) -> "PublicJobPosting":
        """Project a domain posting without provider-specific raw payloads."""

        return cls.model_validate(job.model_dump(mode="json", exclude={"raw_data"}))


class SavedJobResponse(BaseModel):
    """Saved-job response that excludes provider raw data by default."""

    id: str
    job_posting_id: str
    title: str
    company: str
    location: str | None = None
    source: str
    source_url: str | None = None
    apply_url: str | None = None
    job: PublicJobPosting
    job_analysis: JobAnalysis | None = None
    ats_match_report: ATSMatchReport | None = None
    fit_score: float | None = None
    ats_score: float | None = None
    saved_at: datetime
    last_seen_at: datetime
    status: SavedJobStatus
    is_active: bool
    notes: str | None = None

    @classmethod
    def from_domain(cls, saved: SavedJob) -> "SavedJobResponse":
        """Project a saved job into the public API contract."""

        return cls(
            **saved.model_dump(exclude={"job_posting"}),
            job=PublicJobPosting.from_domain(saved.job_posting),
        )


class OptimizationPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: str
    saved_job_id: str
    analyzer_mode: str = "rule_based"
    strict_mode: bool = True


class OptimizationPlanResponse(BaseModel):
    plan_id: str | None = None
    baseline_ats_score: float
    optimization_priority: str
    safe_keywords: list[str]
    unsafe_keywords: list[str]
    forbidden_claims: list[str]
    section_plans: list[dict[str, Any]]
    expected_score_improvement: dict[str, Any]
    warnings: list[str]


class RunOptimizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_id: str
    saved_job_id: str
    options: ResumeOptimizationOptions = Field(default_factory=ResumeOptimizationOptions)
    strict_mode: bool = True
    export_formats: list[str] = Field(default_factory=list)


class ExportedFileResponse(BaseModel):
    file_id: str
    filename: str
    format: str
    byte_size: int
    content_hash: str


class RunOptimizationResponse(BaseModel):
    resume_version_id: str
    target_job_title: str
    target_company: str
    before_ats_score: float
    estimated_after_score: dict[str, float]
    change_count: int
    safety_status: str
    exported_files: list[ExportedFileResponse] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    formats: list[str] = Field(default_factory=lambda: ["pdf"])
    options: dict[str, Any] = Field(default_factory=dict)
    allow_overwrite: bool = False


class ExportResumeResponse(BaseModel):
    version_id: str
    exported_files: list[ExportedFileResponse]
    warnings: list[str] = Field(default_factory=list)


class CreateApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    saved_job_id: str
    resume_version_id: str | None = None
    status: ApplicationStatus = ApplicationStatus.PLANNED
    note: str | None = None


class UpdateApplicationStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ApplicationStatus
    note: str | None = None


class AddApplicationNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str = Field(min_length=1)
    note_type: ApplicationNoteType = ApplicationNoteType.GENERAL


class SetFollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    follow_up_date: date | None


class ApplicationDetailResponse(BaseModel):
    application: JobApplication
    saved_job: SavedJobResponse
    notes: list[ApplicationNote]
    status_history: list[ApplicationStatusHistory]


class ResumeVersionsResponse(BaseModel):
    versions: list[ResumeVersionSummary]


class ApplicationListResponse(BaseModel):
    applications: list[JobApplicationSummary]
