"""Typed contracts for trackable, background-task-ready pipeline runs."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.job_search import JobSearchPreferences


class PipelineRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"


class PipelineStepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PipelineExecutionMode(StrEnum):
    SYNCHRONOUS = "synchronous"
    LOCAL_BACKGROUND = "local_background"
    EXTERNAL_QUEUE_PLACEHOLDER = "external_queue_placeholder"


class PipelineStep(StrEnum):
    LOAD_RESUME = "load_resume"
    GENERATE_PROFILE = "generate_profile"
    GENERATE_QUERIES = "generate_queries"
    SEARCH_JOBS = "search_jobs"
    NORMALIZE_JOBS = "normalize_jobs"
    DEDUPLICATE_JOBS = "deduplicate_jobs"
    RANK_JOBS = "rank_jobs"
    SAVE_JOBS = "save_jobs"
    ANALYZE_JOBS = "analyze_jobs"
    GENERATE_SKILL_GAPS = "generate_skill_gaps"
    SCORE_ATS = "score_ats"
    PLAN_OPTIMIZATION = "plan_optimization"
    OPTIMIZE_RESUMES = "optimize_resumes"
    SAVE_RESUME_VERSIONS = "save_resume_versions"
    EXPORT_RESUMES = "export_resumes"
    CREATE_APPLICATIONS = "create_applications"
    FINALIZE = "finalize"


class PipelineEventType(StrEnum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    WARNING_ADDED = "warning_added"
    ERROR_ADDED = "error_added"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    CANCELLATION_REQUESTED = "cancellation_requested"
    RUN_CANCELLED = "run_cancelled"


class PipelineRunRequest(BaseModel):
    """User-controlled limits and options for one pipeline execution."""

    model_config = ConfigDict(extra="forbid")

    resume_id: str = Field(min_length=1)
    execution_mode: PipelineExecutionMode = PipelineExecutionMode.SYNCHRONOUS
    preferences: JobSearchPreferences = Field(default_factory=JobSearchPreferences)
    max_jobs_to_search: int = Field(default=20, ge=1, le=100)
    max_jobs_to_analyze: int = Field(default=10, ge=0, le=100)
    max_jobs_to_optimize: int = Field(default=3, ge=0, le=20)
    optimization_enabled: bool = True
    export_enabled: bool = True
    export_formats: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    create_applications: bool = False


class PipelineRunResult(BaseModel):
    """Compact persisted result that avoids raw resume and provider payloads."""

    resume_id: str
    jobs_found: int = 0
    saved_job_ids: list[str] = Field(default_factory=list)
    analyzed_job_ids: list[str] = Field(default_factory=list)
    resume_version_ids: list[str] = Field(default_factory=list)
    export_file_ids: list[str] = Field(default_factory=list)
    application_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class PipelineRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    resume_id: str
    status: PipelineRunStatus
    request: PipelineRunRequest
    result: PipelineRunResult | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    current_step: PipelineStep | None = None
    progress_percentage: int = Field(default=0, ge=0, le=100)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    duration_seconds: float | None = Field(default=None, ge=0)
    execution_mode: PipelineExecutionMode
    cancellation_requested: bool = False


class PipelineRunStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    pipeline_run_id: str
    step: PipelineStep
    status: PipelineStepStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    warning_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineRunEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    pipeline_run_id: str
    event_type: PipelineEventType
    step: PipelineStep | None = None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class PipelineSubmissionResult(BaseModel):
    pipeline_run_id: str
    status: PipelineRunStatus
    execution_mode: PipelineExecutionMode
    polling_url: str
    result_url: str
    submitted_at: datetime


class PipelineSearchOutcome(BaseModel):
    jobs_found: int
    saved_job_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PipelineOptimizationOutcome(BaseModel):
    resume_version_id: str
    export_file_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
