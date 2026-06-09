"""Job search, saved-job, and analysis endpoints."""

from fastapi import APIRouter, Query

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import (
    JobSearchRequest,
    JobSearchResponse,
    SavedJobResponse,
)
from ai_internship_assistant.api.workflow import ApiWorkflowService
from ai_internship_assistant.domain.models import JobAnalysis

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponse)
def search_jobs(request: JobSearchRequest, container: ContainerDependency) -> JobSearchResponse:
    """Search configured non-network default sources and rank results."""

    # TODO: move real provider searches to a background task when enabled.
    return ApiWorkflowService(container).search_jobs(request)


@router.get("/saved", response_model=list[SavedJobResponse])
def list_saved_jobs(
    container: ContainerDependency,
    company: str | None = None,
    source: str | None = None,
    active_only: bool = False,
    limit: int = Query(20, ge=1, le=100),
) -> list[SavedJobResponse]:
    """List saved jobs using the tracker service."""

    return [
        SavedJobResponse.from_domain(item)
        for item in container.tracking.list_saved_jobs(
            company=company,
            source=source,
            active_only=active_only,
            limit=limit,
        )
    ]


@router.get("/saved/{saved_job_id}", response_model=SavedJobResponse)
def get_saved_job(saved_job_id: str, container: ContainerDependency) -> SavedJobResponse:
    """Return one saved job detail."""

    return SavedJobResponse.from_domain(container.tracking.get_saved_job(saved_job_id))


@router.post("/{saved_job_id}/analyze", response_model=JobAnalysis)
def analyze_saved_job(saved_job_id: str, container: ContainerDependency) -> JobAnalysis:
    """Run deterministic job-description analysis and persist it."""

    return ApiWorkflowService(container).analyze_saved_job(saved_job_id)
