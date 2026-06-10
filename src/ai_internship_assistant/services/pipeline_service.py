"""Execution-strategy-neutral orchestration for trackable pipeline runs."""

from collections.abc import Callable
from typing import Protocol

from ai_internship_assistant.domain.models import (
    PipelineEventType,
    PipelineExecutionMode,
    PipelineOptimizationOutcome,
    PipelineRun,
    PipelineRunRequest,
    PipelineRunResult,
    PipelineRunStatus,
    PipelineSearchOutcome,
    PipelineStep,
    PipelineStepStatus,
    PipelineSubmissionResult,
)
from ai_internship_assistant.storage import PipelineRunRepository


class PipelineCancelledError(RuntimeError):
    """Internal control-flow signal raised between steps after cancellation."""


class UnsupportedPipelineExecutionModeError(ValueError):
    """Raised when an execution strategy is not available in this process."""


class PipelineOperations(Protocol):
    """Adapter boundary between orchestration and existing application workflows."""

    def load_resume(self, resume_id: str) -> None: ...
    def generate_profile(self, resume_id: str) -> None: ...
    def search_jobs(self, request: PipelineRunRequest) -> PipelineSearchOutcome: ...
    def analyze_job(self, saved_job_id: str) -> None: ...
    def optimize_job(
        self, resume_id: str, saved_job_id: str, export_formats: list[str]
    ) -> PipelineOptimizationOutcome: ...
    def create_application(self, saved_job_id: str, resume_version_id: str | None) -> str: ...


class PipelineProgressTracker:
    """Own durable state transitions, bounded progress, and privacy-safe events."""

    def __init__(
        self,
        repository: PipelineRunRepository,
        *,
        store_events: bool = True,
        max_events_per_run: int = 500,
    ) -> None:
        self._repository = repository
        self._store_events = store_events
        self._max_events = max_events_per_run

    def start_run(self, run_id: str) -> None:
        run = self._repository.start_run(run_id)
        if run.status is PipelineRunStatus.CANCELLED:
            self._event(run_id, PipelineEventType.RUN_CANCELLED, "Pipeline run cancelled.")
            raise PipelineCancelledError
        self._event(run_id, PipelineEventType.RUN_STARTED, "Pipeline run started.")

    def start_step(self, run_id: str, step: PipelineStep) -> None:
        self.raise_if_cancelled(run_id)
        self._repository.start_step(run_id, step)
        self._event(run_id, PipelineEventType.STEP_STARTED, f"Step started: {step.value}.", step)

    def complete_step(
        self,
        run_id: str,
        step: PipelineStep,
        *,
        metadata: dict[str, object] | None = None,
        warning_count: int = 0,
        error_count: int = 0,
        skipped: bool = False,
    ) -> None:
        status = PipelineStepStatus.SKIPPED if skipped else PipelineStepStatus.COMPLETED
        self._repository.finish_step(
            run_id,
            step,
            status,
            metadata=metadata,
            warning_count=warning_count,
            error_count=error_count,
        )
        finished = sum(
            record.status
            in {PipelineStepStatus.COMPLETED, PipelineStepStatus.SKIPPED, PipelineStepStatus.FAILED}
            for record in self._repository.list_steps(run_id)
        )
        self._repository.update_progress(run_id, round(finished * 100 / len(PipelineStep)))
        label = "skipped" if skipped else "completed"
        self._event(run_id, PipelineEventType.STEP_COMPLETED, f"Step {label}: {step.value}.", step)

    def fail_step(self, run_id: str, step: PipelineStep, message: str) -> None:
        self._repository.finish_step(
            run_id, step, PipelineStepStatus.FAILED, error_count=1
        )
        self.add_error(run_id, message, step=step)
        self._event(run_id, PipelineEventType.STEP_FAILED, f"Step failed: {step.value}.", step)

    def add_warning(self, run_id: str, message: str, *, step: PipelineStep | None = None) -> None:
        self._repository.add_warning(run_id, message)
        self._event(run_id, PipelineEventType.WARNING_ADDED, message, step)

    def add_error(self, run_id: str, message: str, *, step: PipelineStep | None = None) -> None:
        self._repository.add_error(run_id, message)
        self._event(run_id, PipelineEventType.ERROR_ADDED, message, step)

    def finish(self, run_id: str, result: PipelineRunResult) -> PipelineRun:
        status = (
            PipelineRunStatus.PARTIAL_SUCCESS
            if self._repository.get(run_id).errors
            else PipelineRunStatus.COMPLETED
        )
        run = self._repository.finish_run(run_id, status, result)
        self._event(run_id, PipelineEventType.RUN_COMPLETED, f"Pipeline run {status.value}.")
        return run

    def fail(self, run_id: str, result: PipelineRunResult) -> PipelineRun:
        run = self._repository.finish_run(run_id, PipelineRunStatus.FAILED, result)
        self._event(run_id, PipelineEventType.RUN_FAILED, "Pipeline run failed.")
        return run

    def raise_if_cancelled(self, run_id: str) -> None:
        run = self._repository.get(run_id)
        if run.cancellation_requested:
            self._repository.finish_run(run_id, PipelineRunStatus.CANCELLED, run.result)
            self._event(run_id, PipelineEventType.RUN_CANCELLED, "Pipeline run cancelled.")
            raise PipelineCancelledError

    def _event(
        self,
        run_id: str,
        event_type: PipelineEventType,
        message: str,
        step: PipelineStep | None = None,
    ) -> None:
        if self._store_events and len(
            self._repository.list_events(run_id, limit=self._max_events)
        ) < self._max_events:
            self._repository.add_event(run_id, event_type, message, step=step)


class PipelineExecutor:
    """Submit and execute runs independently of HTTP or queue strategy."""

    def __init__(
        self,
        repository: PipelineRunRepository,
        operations: PipelineOperations,
        tracker: PipelineProgressTracker,
        *,
        local_background_enabled: bool = True,
    ) -> None:
        self._repository = repository
        self._operations = operations
        self._tracker = tracker
        self._local_background_enabled = local_background_enabled

    def submit(self, request: PipelineRunRequest) -> PipelineSubmissionResult:
        if request.execution_mode is PipelineExecutionMode.EXTERNAL_QUEUE_PLACEHOLDER:
            raise UnsupportedPipelineExecutionModeError(
                "external queue execution is not implemented"
            )
        if (
            request.execution_mode is PipelineExecutionMode.LOCAL_BACKGROUND
            and not self._local_background_enabled
        ):
            raise UnsupportedPipelineExecutionModeError("local background execution is disabled")
        run = self._repository.create(request)
        self._repository.add_event(run.id, PipelineEventType.RUN_CREATED, "Pipeline run created.")
        if request.execution_mode is PipelineExecutionMode.SYNCHRONOUS:
            run = self.run_now(run.id)
        return PipelineSubmissionResult(
            pipeline_run_id=run.id,
            status=run.status,
            execution_mode=run.execution_mode,
            polling_url=f"/pipeline/runs/{run.id}",
            result_url=f"/pipeline/runs/{run.id}/result",
            submitted_at=run.created_at,
        )

    def run_now(self, run_id: str) -> PipelineRun:
        run = self._repository.get(run_id)
        result = PipelineRunResult(resume_id=run.resume_id)
        current: PipelineStep | None = None
        try:
            self._tracker.start_run(run_id)
            current = PipelineStep.LOAD_RESUME
            self._run_required(run_id, current, lambda: self._operations.load_resume(run.resume_id))
            current = PipelineStep.GENERATE_PROFILE
            self._run_required(
                run_id, current, lambda: self._operations.generate_profile(run.resume_id)
            )
            self._markers(run_id, [PipelineStep.GENERATE_QUERIES], "Handled by job search.")

            current = PipelineStep.SEARCH_JOBS
            self._tracker.start_step(run_id, current)
            search = self._operations.search_jobs(run.request)
            result.jobs_found = search.jobs_found
            result.saved_job_ids = search.saved_job_ids
            for warning in search.warnings:
                result.warnings.append(warning)
                self._tracker.add_warning(run_id, warning, step=current)
            self._tracker.complete_step(
                run_id,
                current,
                metadata={"jobs_found": search.jobs_found, "saved_jobs": len(search.saved_job_ids)},
                warning_count=len(search.warnings),
            )
            self._markers(
                run_id,
                [
                    PipelineStep.NORMALIZE_JOBS,
                    PipelineStep.DEDUPLICATE_JOBS,
                    PipelineStep.RANK_JOBS,
                    PipelineStep.SAVE_JOBS,
                ],
                "Handled by job search.",
            )
            self._analyze(run, result)
            self._markers(
                run_id,
                [
                    PipelineStep.GENERATE_SKILL_GAPS,
                    PipelineStep.SCORE_ATS,
                    PipelineStep.PLAN_OPTIMIZATION,
                ],
                "Handled by optimization.",
                skipped=not run.request.optimization_enabled,
            )
            self._optimize(run, result)
            self._markers(
                run_id,
                [PipelineStep.SAVE_RESUME_VERSIONS, PipelineStep.EXPORT_RESUMES],
                "Handled by optimization.",
                skipped=not run.request.optimization_enabled,
            )
            self._applications(run, result)
            current = PipelineStep.FINALIZE
            self._run_required(run_id, current, lambda: None)
            result.errors = self._repository.get(run_id).errors
            return self._tracker.finish(run_id, result)
        except PipelineCancelledError:
            return self._repository.get(run_id)
        except Exception:
            message = "required pipeline step failed"
            result.errors.append(message)
            if current is not None:
                self._tracker.fail_step(run_id, current, message)
            else:
                self._tracker.add_error(run_id, message)
            return self._tracker.fail(run_id, result)

    def cancel(self, run_id: str) -> PipelineRun:
        run = self._repository.request_cancellation(run_id)
        self._repository.add_event(
            run_id, PipelineEventType.CANCELLATION_REQUESTED, "Pipeline cancellation requested."
        )
        if run.status is PipelineRunStatus.CANCELLED:
            self._repository.add_event(
                run_id, PipelineEventType.RUN_CANCELLED, "Pending pipeline run cancelled."
            )
        return run

    def _run_required(
        self, run_id: str, step: PipelineStep, operation: Callable[[], object]
    ) -> None:
        self._tracker.start_step(run_id, step)
        operation()
        self._tracker.complete_step(run_id, step)

    def _analyze(self, run: PipelineRun, result: PipelineRunResult) -> None:
        step = PipelineStep.ANALYZE_JOBS
        self._tracker.start_step(run.id, step)
        failures = 0
        for job_id in result.saved_job_ids[: run.request.max_jobs_to_analyze]:
            self._tracker.raise_if_cancelled(run.id)
            try:
                self._operations.analyze_job(job_id)
                result.analyzed_job_ids.append(job_id)
            except Exception:
                failures += 1
                message = f"job analysis failed for saved job {job_id}"
                result.errors.append(message)
                self._tracker.add_error(run.id, message, step=step)
        self._tracker.complete_step(
            run.id,
            step,
            metadata={"analyzed_jobs": len(result.analyzed_job_ids)},
            error_count=failures,
        )

    def _optimize(self, run: PipelineRun, result: PipelineRunResult) -> None:
        step = PipelineStep.OPTIMIZE_RESUMES
        self._tracker.start_step(run.id, step)
        if not run.request.optimization_enabled:
            self._tracker.complete_step(run.id, step, skipped=True)
            return
        failures = 0
        formats = run.request.export_formats if run.request.export_enabled else []
        for job_id in result.saved_job_ids[: run.request.max_jobs_to_optimize]:
            self._tracker.raise_if_cancelled(run.id)
            try:
                outcome = self._operations.optimize_job(run.resume_id, job_id, formats)
                result.resume_version_ids.append(outcome.resume_version_id)
                result.export_file_ids.extend(outcome.export_file_ids)
                for warning in outcome.warnings:
                    result.warnings.append(warning)
                    self._tracker.add_warning(run.id, warning, step=step)
            except Exception:
                failures += 1
                message = f"resume optimization failed for saved job {job_id}"
                result.errors.append(message)
                self._tracker.add_error(run.id, message, step=step)
        self._tracker.complete_step(
            run.id,
            step,
            metadata={"resume_versions": len(result.resume_version_ids)},
            error_count=failures,
        )

    def _applications(self, run: PipelineRun, result: PipelineRunResult) -> None:
        step = PipelineStep.CREATE_APPLICATIONS
        self._tracker.start_step(run.id, step)
        if not run.request.create_applications:
            self._tracker.complete_step(run.id, step, skipped=True)
            return
        for index, job_id in enumerate(result.saved_job_ids):
            self._tracker.raise_if_cancelled(run.id)
            version_id = (
                result.resume_version_ids[index]
                if index < len(result.resume_version_ids)
                else None
            )
            result.application_ids.append(self._operations.create_application(job_id, version_id))
        self._tracker.complete_step(
            run.id, step, metadata={"applications": len(result.application_ids)}
        )

    def _markers(
        self, run_id: str, steps: list[PipelineStep], message: str, *, skipped: bool = False
    ) -> None:
        for step in steps:
            self._tracker.start_step(run_id, step)
            self._tracker.complete_step(
                run_id, step, metadata={"execution_note": message}, skipped=skipped
            )
