"""Trackable pipeline submission, polling, result, and cancellation endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Query, Response, status

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import (
    PipelineResultNotReady,
    PipelineResultResponse,
    PipelineRunSummary,
)
from ai_internship_assistant.domain.models import (
    PipelineExecutionMode,
    PipelineRunEvent,
    PipelineRunRequest,
    PipelineRunStatus,
    PipelineRunStepRecord,
    PipelineSubmissionResult,
)

router = APIRouter(prefix="/pipeline/runs", tags=["pipeline"])


@router.post("", response_model=PipelineSubmissionResult, status_code=201)
def submit_pipeline_run(
    request: PipelineRunRequest,
    background_tasks: BackgroundTasks,
    container: ContainerDependency,
) -> PipelineSubmissionResult:
    """Persist and start one synchronous or local-background pipeline run."""

    submission = container.pipeline_executor.submit(request)
    if request.execution_mode is PipelineExecutionMode.LOCAL_BACKGROUND:
        background_tasks.add_task(container.pipeline_executor.run_now, submission.pipeline_run_id)
    return submission


@router.get("", response_model=list[PipelineRunSummary])
def list_pipeline_runs(
    container: ContainerDependency,
    run_status: Annotated[PipelineRunStatus | None, Query(alias="status")] = None,
    resume_id: str | None = None,
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> list[PipelineRunSummary]:
    """List lightweight pipeline run summaries."""

    return [
        PipelineRunSummary.from_domain(run)
        for run in container.pipeline_runs.list_runs(
            status=run_status,
            resume_id=resume_id,
            created_after=created_after,
            created_before=created_before,
            limit=limit,
        )
    ]


@router.get("/{pipeline_run_id}", response_model=PipelineRunSummary)
def get_pipeline_run(pipeline_run_id: str, container: ContainerDependency) -> PipelineRunSummary:
    """Return current run status and progress."""

    return PipelineRunSummary.from_domain(container.pipeline_runs.get(pipeline_run_id))


@router.get("/{pipeline_run_id}/steps", response_model=list[PipelineRunStepRecord])
def get_pipeline_steps(
    pipeline_run_id: str, container: ContainerDependency
) -> list[PipelineRunStepRecord]:
    """Return canonical step records in execution order."""

    return container.pipeline_runs.list_steps(pipeline_run_id)


@router.get("/{pipeline_run_id}/events", response_model=list[PipelineRunEvent])
def get_pipeline_events(
    pipeline_run_id: str, container: ContainerDependency
) -> list[PipelineRunEvent]:
    """Return the privacy-safe pipeline timeline."""

    return container.pipeline_runs.list_events(
        pipeline_run_id,
        limit=container.settings.pipeline_max_stored_events_per_run,
    )


@router.get("/{pipeline_run_id}/result", response_model=PipelineResultResponse)
def get_pipeline_result(
    pipeline_run_id: str,
    response: Response,
    container: ContainerDependency,
) -> PipelineResultResponse:
    """Return the compact final result or a structured not-ready response."""

    run = container.pipeline_runs.get(pipeline_run_id)
    if run.result is not None:
        return run.result
    response.status_code = status.HTTP_202_ACCEPTED
    return PipelineResultNotReady(
        pipeline_run_id=run.id,
        status=run.status,
        errors=run.errors if run.status is PipelineRunStatus.FAILED else [],
    )


@router.post("/{pipeline_run_id}/cancel", response_model=PipelineRunSummary)
def cancel_pipeline_run(
    pipeline_run_id: str, container: ContainerDependency
) -> PipelineRunSummary:
    """Request cooperative cancellation between major pipeline steps."""

    return PipelineRunSummary.from_domain(container.pipeline_executor.cancel(pipeline_run_id))
