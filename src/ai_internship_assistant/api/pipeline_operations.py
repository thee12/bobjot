"""Adapter from the generic pipeline executor to existing API-composed services."""

from typing import TYPE_CHECKING

from ai_internship_assistant.api.schemas import JobSearchRequest, RunOptimizationRequest
from ai_internship_assistant.domain.models import (
    ApplicationStatus,
    PipelineOptimizationOutcome,
    PipelineRunRequest,
    PipelineSearchOutcome,
)

if TYPE_CHECKING:
    from ai_internship_assistant.api.dependencies import ApiContainer


class ApiPipelineOperations:
    """Use existing workflow services without coupling the executor to FastAPI."""

    def __init__(self, container: "ApiContainer") -> None:
        self._container = container

    def load_resume(self, resume_id: str) -> None:
        self._container.versioning.get_master_resume(resume_id)

    def generate_profile(self, resume_id: str) -> None:
        from ai_internship_assistant.api.workflow import ApiWorkflowService

        stored = self._container.versioning.get_master_resume(resume_id)
        ApiWorkflowService(self._container).profile_for_resume(stored)

    def search_jobs(self, request: PipelineRunRequest) -> PipelineSearchOutcome:
        from ai_internship_assistant.api.workflow import ApiWorkflowService

        response = ApiWorkflowService(self._container).search_jobs(
            JobSearchRequest(
                resume_id=request.resume_id,
                preferences=request.preferences,
                max_results=request.max_jobs_to_search,
                include_rankings=True,
                save_results=True,
            )
        )
        saved = self._container.tracking.list_saved_jobs(limit=request.max_jobs_to_search)
        return PipelineSearchOutcome(
            jobs_found=response.total_unique_jobs,
            saved_job_ids=[item.id for item in saved],
            warnings=response.warnings,
        )

    def analyze_job(self, saved_job_id: str) -> None:
        from ai_internship_assistant.api.workflow import ApiWorkflowService

        ApiWorkflowService(self._container).analyze_saved_job(saved_job_id)

    def optimize_job(
        self,
        resume_id: str,
        saved_job_id: str,
        export_formats: list[str],
    ) -> PipelineOptimizationOutcome:
        from ai_internship_assistant.api.workflow import ApiWorkflowService

        result = ApiWorkflowService(self._container).run_optimization(
            RunOptimizationRequest(
                resume_id=resume_id,
                saved_job_id=saved_job_id,
                export_formats=export_formats,
            )
        )
        return PipelineOptimizationOutcome(
            resume_version_id=result.resume_version_id,
            export_file_ids=[item.file_id for item in result.exported_files],
            warnings=result.warnings,
        )

    def create_application(self, saved_job_id: str, resume_version_id: str | None) -> str:
        application = self._container.tracking.create_application(
            saved_job_id,
            resume_version_id,
            ApplicationStatus.PLANNED,
        )
        return application.id
