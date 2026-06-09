"""Application tracker HTTP endpoints."""

from datetime import date

from fastapi import APIRouter, Query

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import (
    AddApplicationNoteRequest,
    ApplicationDetailResponse,
    CreateApplicationRequest,
    SavedJobResponse,
    SetFollowUpRequest,
    UpdateApplicationStatusRequest,
)
from ai_internship_assistant.domain.models import (
    ApplicationFilters,
    ApplicationNote,
    ApplicationStatus,
    JobApplication,
    JobApplicationSummary,
)

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=JobApplication, status_code=201)
def create_application(
    request: CreateApplicationRequest,
    container: ContainerDependency,
) -> JobApplication:
    """Create an application from a saved job."""

    return container.tracking.create_application(
        request.saved_job_id,
        request.resume_version_id,
        request.status,
        notes=request.note,
    )


@router.get("", response_model=list[JobApplicationSummary])
def list_applications(
    container: ContainerDependency,
    status: ApplicationStatus | None = None,
    company: str | None = None,
    role: str | None = None,
    needs_follow_up: bool | None = None,
    has_interview: bool | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> list[JobApplicationSummary]:
    """List lightweight application summaries."""

    return container.tracking.list_applications(
        ApplicationFilters(
            status=status,
            company=company,
            role_keyword=role,
            needs_follow_up=needs_follow_up,
            has_interview=has_interview,
        ),
        limit=limit,
    )


@router.get("/due", response_model=list[JobApplicationSummary])
def due_applications(
    container: ContainerDependency,
    as_of: date | None = None,
) -> list[JobApplicationSummary]:
    """List applications with due follow-up dates."""

    return container.tracking.list_follow_ups_due(as_of_date=as_of)


@router.get("/{application_id}", response_model=ApplicationDetailResponse)
def get_application(
    application_id: str,
    container: ContainerDependency,
) -> ApplicationDetailResponse:
    """Return application detail, notes, saved job, and history."""

    application = container.tracking.get_application(application_id)
    return ApplicationDetailResponse(
        application=application,
        saved_job=SavedJobResponse.from_domain(
            container.tracking.get_saved_job(application.saved_job_id)
        ),
        notes=container.tracking.list_application_notes(application_id),
        status_history=container.tracking.get_application_history(application_id),
    )


@router.patch("/{application_id}/status", response_model=JobApplication)
def update_application_status(
    application_id: str,
    request: UpdateApplicationStatusRequest,
    container: ContainerDependency,
) -> JobApplication:
    """Update application status and status history."""

    return container.tracking.update_application_status(
        application_id,
        request.status,
        request.note,
    )


@router.post("/{application_id}/notes", response_model=ApplicationNote, status_code=201)
def add_application_note(
    application_id: str,
    request: AddApplicationNoteRequest,
    container: ContainerDependency,
) -> ApplicationNote:
    """Append one typed application note."""

    return container.tracking.add_application_note(
        application_id,
        request.note,
        request.note_type,
    )


@router.patch("/{application_id}/follow-up", response_model=JobApplication)
def set_follow_up(
    application_id: str,
    request: SetFollowUpRequest,
    container: ContainerDependency,
) -> JobApplication:
    """Set or clear an application follow-up date."""

    return container.tracking.set_follow_up_date(application_id, request.follow_up_date)
