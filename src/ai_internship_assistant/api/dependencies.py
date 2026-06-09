"""FastAPI dependency construction and application-scoped service container."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, cast

from fastapi import Depends, Request
from openai import OpenAI

from ai_internship_assistant.config import AppSettings
from ai_internship_assistant.domain.models import Resume
from ai_internship_assistant.services import (
    ApplicationTrackingService,
    ATSMatchScoringService,
    CandidateProfilePipeline,
    DocxResumeRenderer,
    FullResumeOptimizer,
    JobFitScoringService,
    JobSearchQueryGenerator,
    JobSearchService,
    MarkdownResumeRenderer,
    MockJobSource,
    OpenAIResumeParser,
    PdfResumeRenderer,
    ResumeOptimizationPlanner,
    ResumeParser,
    ResumeVersioningService,
    RuleBasedJobDescriptionAnalyzer,
    RuleBasedResumeBulletRewriter,
    SkillGapAnalyzer,
)
from ai_internship_assistant.storage import (
    ApplicationRepository,
    Database,
    JobRepository,
    MasterResumeRepository,
    ResumeVersionRepository,
    SavedJobRepository,
)


class ResumeParserUnavailableError(RuntimeError):
    """Raised when upload parsing is requested without a configured parser."""


class UnavailableResumeParser:
    """Default parser boundary for local API mode without LLM configuration."""

    def parse(self, text: str) -> Resume:
        raise ResumeParserUnavailableError(
            "resume parser is unavailable; configure an LLM parser or override the API dependency"
        )


@dataclass(frozen=True)
class ExportArtifact:
    """Safe application-scoped mapping from opaque file ID to generated artifact."""

    path: Path
    filename: str
    media_type: str


@dataclass
class ApiContainer:
    """Application-scoped dependencies used by thin routers."""

    settings: AppSettings
    database: Database
    masters: MasterResumeRepository
    versions: ResumeVersionRepository
    jobs: JobRepository
    saved_jobs: SavedJobRepository
    applications: ApplicationRepository
    versioning: ResumeVersioningService
    tracking: ApplicationTrackingService
    profile_pipeline: CandidateProfilePipeline
    resume_parser: ResumeParser
    job_search: JobSearchService
    query_generator: JobSearchQueryGenerator
    job_ranker: JobFitScoringService
    job_analyzer: RuleBasedJobDescriptionAnalyzer
    gap_analyzer: SkillGapAnalyzer
    ats_scorer: ATSMatchScoringService
    planner: ResumeOptimizationPlanner
    optimizer: FullResumeOptimizer
    markdown_renderer: MarkdownResumeRenderer
    docx_renderer: DocxResumeRenderer
    pdf_renderer: PdfResumeRenderer
    export_dir: Path
    exports: dict[str, ExportArtifact] = field(default_factory=dict)


def build_container(
    *,
    settings: AppSettings | None = None,
    resume_parser: ResumeParser | None = None,
) -> ApiContainer:
    """Construct one testable API dependency graph without global service state."""

    resolved = _apply_jobbot_aliases(settings or AppSettings())
    database_url = os.getenv("JOBBOT_DATABASE_URL") or resolved.database_url
    export_dir = Path(os.getenv("JOBBOT_EXPORT_DIR") or resolved.resume_output_dir)
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    database = Database(database_url)
    database.initialize()
    masters = MasterResumeRepository(database)
    versions = ResumeVersionRepository(database)
    jobs = JobRepository(database)
    saved_jobs = SavedJobRepository(database)
    applications = ApplicationRepository(database)
    return ApiContainer(
        settings=resolved,
        database=database,
        masters=masters,
        versions=versions,
        jobs=jobs,
        saved_jobs=saved_jobs,
        applications=applications,
        versioning=ResumeVersioningService(masters, versions, jobs),
        tracking=ApplicationTrackingService(saved_jobs, applications, versions),
        profile_pipeline=CandidateProfilePipeline(),
        resume_parser=resume_parser or _configured_resume_parser(resolved),
        job_search=JobSearchService([MockJobSource()], normalize=True, deduplicate=True),
        query_generator=JobSearchQueryGenerator(),
        job_ranker=JobFitScoringService(),
        job_analyzer=RuleBasedJobDescriptionAnalyzer(),
        gap_analyzer=SkillGapAnalyzer(),
        ats_scorer=ATSMatchScoringService(),
        planner=ResumeOptimizationPlanner(),
        optimizer=FullResumeOptimizer(RuleBasedResumeBulletRewriter()),
        markdown_renderer=MarkdownResumeRenderer(),
        docx_renderer=DocxResumeRenderer(),
        pdf_renderer=PdfResumeRenderer(),
        export_dir=export_dir,
    )


def _apply_jobbot_aliases(settings: AppSettings) -> AppSettings:
    """Apply concise API-facing environment aliases over typed settings."""

    updates: dict[str, object] = {}
    if value := os.getenv("JOBBOT_ENV"):
        updates["env"] = value
    if value := os.getenv("JOBBOT_ENABLE_LLM"):
        updates["enable_llm_analysis"] = value.casefold() in {"1", "true", "yes", "on"}
    if value := os.getenv("JOBBOT_OPENAI_MODEL"):
        updates["job_analysis_model"] = value
    return settings.model_copy(update=updates)


def _configured_resume_parser(settings: AppSettings) -> ResumeParser:
    """Build the configured upload parser without making a provider call."""

    if settings.enable_llm_analysis and settings.openai_api_key is not None:
        return OpenAIResumeParser(
            client=OpenAI(api_key=settings.openai_api_key.get_secret_value()),
            model=settings.job_analysis_model,
        )
    return UnavailableResumeParser()


def get_container(request: Request) -> ApiContainer:
    """Return the application-scoped dependency container."""

    return cast(ApiContainer, request.app.state.container)


ContainerDependency = Annotated[ApiContainer, Depends(get_container)]
