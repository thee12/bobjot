"""Tests for durable, pollable, cancellation-ready pipeline runs."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_internship_assistant.api.dependencies import ApiContainer, build_container
from ai_internship_assistant.api.main import create_app
from ai_internship_assistant.config import AppSettings
from ai_internship_assistant.domain.models import (
    PipelineExecutionMode,
    PipelineOptimizationOutcome,
    PipelineRunRequest,
    PipelineRunStatus,
    PipelineSearchOutcome,
    PipelineStep,
    PipelineStepStatus,
)
from ai_internship_assistant.services import PipelineExecutor, PipelineProgressTracker
from ai_internship_assistant.storage import (
    Database,
    PipelineRunRepository,
    PipelineRunStateError,
)
from tests.test_full_resume_optimizer import _resume


class FakePipelineOperations:
    """Controllable provider-free operations for executor tests."""

    def __init__(
        self,
        *,
        fail_required: bool = False,
        fail_analysis: bool = False,
        cancel_repository: PipelineRunRepository | None = None,
        cancel_run_id: str | None = None,
    ) -> None:
        self.fail_required = fail_required
        self.fail_analysis = fail_analysis
        self.cancel_repository = cancel_repository
        self.cancel_run_id = cancel_run_id

    def load_resume(self, resume_id: str) -> None:
        if self.fail_required:
            raise RuntimeError("provider detail must not escape")

    def generate_profile(self, resume_id: str) -> None:
        if self.cancel_repository is not None and self.cancel_run_id is not None:
            self.cancel_repository.request_cancellation(self.cancel_run_id)

    def search_jobs(self, request: PipelineRunRequest) -> PipelineSearchOutcome:
        return PipelineSearchOutcome(jobs_found=1, saved_job_ids=["saved-1"], warnings=["notice"])

    def analyze_job(self, saved_job_id: str) -> None:
        if self.fail_analysis:
            raise RuntimeError("private provider detail")

    def optimize_job(
        self,
        resume_id: str,
        saved_job_id: str,
        export_formats: list[str],
    ) -> PipelineOptimizationOutcome:
        return PipelineOptimizationOutcome(
            resume_version_id="version-1",
            export_file_ids=["file-1"] if export_formats else [],
        )

    def create_application(self, saved_job_id: str, resume_version_id: str | None) -> str:
        return "application-1"


@pytest.fixture
def repository() -> PipelineRunRepository:
    database = Database("sqlite://")
    database.initialize()
    return PipelineRunRepository(database)


def _executor(
    repository: PipelineRunRepository,
    operations: FakePipelineOperations | None = None,
) -> PipelineExecutor:
    return PipelineExecutor(
        repository,
        operations or FakePipelineOperations(),
        PipelineProgressTracker(repository),
    )


def test_create_pipeline_run_initializes_pending_steps(repository: PipelineRunRepository) -> None:
    run = repository.create(PipelineRunRequest(resume_id="resume-1"))

    assert run.status is PipelineRunStatus.PENDING
    assert run.progress_percentage == 0
    assert len(repository.list_steps(run.id)) == len(PipelineStep)
    assert all(step.status is PipelineStepStatus.PENDING for step in repository.list_steps(run.id))


def test_synchronous_pipeline_completes_and_persists_result(
    repository: PipelineRunRepository,
) -> None:
    submission = _executor(repository).submit(PipelineRunRequest(resume_id="resume-1"))
    run = repository.get(submission.pipeline_run_id)

    assert submission.status is PipelineRunStatus.COMPLETED
    assert run.progress_percentage == 100
    assert run.result is not None
    assert run.result.resume_version_ids == ["version-1"]
    assert run.duration_seconds is not None
    assert all(step.duration_seconds is not None for step in repository.list_steps(run.id))


def test_recoverable_failure_becomes_partial_success(repository: PipelineRunRepository) -> None:
    executor = _executor(repository, FakePipelineOperations(fail_analysis=True))
    submission = executor.submit(PipelineRunRequest(resume_id="resume-1"))
    run = repository.get(submission.pipeline_run_id)

    assert run.status is PipelineRunStatus.PARTIAL_SUCCESS
    assert run.result is not None
    assert run.result.errors == ["job analysis failed for saved job saved-1"]
    assert "private provider detail" not in run.model_dump_json()


def test_required_failure_becomes_failed_without_private_error(
    repository: PipelineRunRepository,
) -> None:
    executor = _executor(repository, FakePipelineOperations(fail_required=True))
    submission = executor.submit(PipelineRunRequest(resume_id="resume-1"))
    run = repository.get(submission.pipeline_run_id)

    assert run.status is PipelineRunStatus.FAILED
    assert run.progress_percentage < 100
    assert run.errors == ["required pipeline step failed"]
    assert "provider detail" not in run.model_dump_json()


def test_pending_run_can_be_cancelled(repository: PipelineRunRepository) -> None:
    request = PipelineRunRequest(
        resume_id="resume-1",
        execution_mode=PipelineExecutionMode.LOCAL_BACKGROUND,
    )
    executor = _executor(repository)
    submission = executor.submit(request)
    run = executor.cancel(submission.pipeline_run_id)

    assert run.status is PipelineRunStatus.CANCELLED
    assert run.cancellation_requested is True


def test_running_run_checks_cancellation_between_steps(repository: PipelineRunRepository) -> None:
    request = PipelineRunRequest(
        resume_id="resume-1",
        execution_mode=PipelineExecutionMode.LOCAL_BACKGROUND,
    )
    run = repository.create(request)
    operations = FakePipelineOperations(cancel_repository=repository, cancel_run_id=run.id)

    result = _executor(repository, operations).run_now(run.id)

    assert result.status is PipelineRunStatus.CANCELLED
    assert result.progress_percentage < 100


def test_completed_run_cannot_be_cancelled(repository: PipelineRunRepository) -> None:
    executor = _executor(repository)
    submission = executor.submit(PipelineRunRequest(resume_id="resume-1"))

    with pytest.raises(PipelineRunStateError):
        executor.cancel(submission.pipeline_run_id)


def test_progress_is_clamped(repository: PipelineRunRepository) -> None:
    run = repository.create(PipelineRunRequest(resume_id="resume-1"))

    assert repository.update_progress(run.id, -10).progress_percentage == 0
    assert repository.update_progress(run.id, 120).progress_percentage == 100


@pytest.fixture
def pipeline_api(tmp_path: Path) -> tuple[TestClient, ApiContainer, str]:
    settings = AppSettings(
        database_url=f"sqlite:///{(tmp_path / 'pipeline.db').as_posix()}",
        resume_output_dir=str(tmp_path / "exports"),
    )
    container = build_container(settings=settings)
    resume_id = container.versioning.save_master_resume(_resume()).id
    client = TestClient(create_app(container), raise_server_exceptions=False)
    return client, container, resume_id


def test_pipeline_api_submit_poll_steps_events_and_result(
    pipeline_api: tuple[TestClient, ApiContainer, str],
) -> None:
    client, _, resume_id = pipeline_api
    submitted = client.post(
        "/pipeline/runs",
        json={
            "resume_id": resume_id,
            "optimization_enabled": False,
            "export_enabled": False,
        },
    )
    run_id = submitted.json()["pipeline_run_id"]

    assert submitted.status_code == 201
    assert submitted.json()["status"] in {"completed", "partial_success"}
    assert client.get("/pipeline/runs").json()[0]["id"] == run_id
    assert client.get(f"/pipeline/runs/{run_id}").json()["progress_percentage"] == 100
    assert len(client.get(f"/pipeline/runs/{run_id}/steps").json()) == len(PipelineStep)
    assert client.get(f"/pipeline/runs/{run_id}/events").json()
    assert client.get(f"/pipeline/runs/{run_id}/result").status_code == 200


def test_pipeline_api_not_ready_missing_invalid_and_no_traceback(
    pipeline_api: tuple[TestClient, ApiContainer, str],
) -> None:
    client, container, resume_id = pipeline_api
    pending = container.pipeline_runs.create(
        PipelineRunRequest(
            resume_id=resume_id,
            execution_mode=PipelineExecutionMode.LOCAL_BACKGROUND,
        )
    )

    assert client.get(f"/pipeline/runs/{pending.id}/result").status_code == 202
    missing = client.get("/pipeline/runs/missing")
    assert missing.status_code == 404
    assert "Traceback" not in missing.text
    invalid = client.post(
        "/pipeline/runs",
        json={"resume_id": resume_id, "execution_mode": "not-a-mode"},
    )
    assert invalid.status_code == 422
    external = client.post(
        "/pipeline/runs",
        json={"resume_id": resume_id, "execution_mode": "external_queue_placeholder"},
    )
    assert external.status_code == 400


def test_pipeline_api_local_background_executes_same_workflow(
    pipeline_api: tuple[TestClient, ApiContainer, str],
) -> None:
    client, _, resume_id = pipeline_api
    submitted = client.post(
        "/pipeline/runs",
        json={
            "resume_id": resume_id,
            "execution_mode": "local_background",
            "optimization_enabled": False,
        },
    )
    run = client.get(submitted.json()["polling_url"])

    assert submitted.status_code == 201
    assert submitted.json()["status"] == "pending"
    assert run.json()["status"] in {"completed", "partial_success"}
