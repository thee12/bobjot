"""Persistence for pipeline runs, canonical steps, and timeline events."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_internship_assistant.domain.models import (
    PipelineEventType,
    PipelineRun,
    PipelineRunEvent,
    PipelineRunRequest,
    PipelineRunResult,
    PipelineRunStatus,
    PipelineRunStepRecord,
    PipelineStep,
    PipelineStepStatus,
)
from ai_internship_assistant.storage.database import (
    Database,
    PipelineRunEventRow,
    PipelineRunRow,
    PipelineRunStepRow,
)
from ai_internship_assistant.storage.repositories import CorruptedArtifactError, PersistenceError
from ai_internship_assistant.storage.serialization import (
    ArtifactSerializationError,
    deserialize_model,
    serialize_model,
)


class PipelineRunNotFoundError(PersistenceError):
    """Raised when a pipeline run does not exist."""


class PipelineRunStateError(PersistenceError):
    """Raised for invalid pipeline state transitions."""


class PipelineRunRepository:
    """Store durable pipeline state independently from execution strategy."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(self, request: PipelineRunRequest) -> PipelineRun:
        now = datetime.now(UTC)
        run_id = str(uuid4())
        with self._database.session() as session:
            session.add(
                PipelineRunRow(
                    id=run_id,
                    resume_id=request.resume_id,
                    status=PipelineRunStatus.PENDING.value,
                    request_json=serialize_model(request),
                    result_json=None,
                    error_summary_json="[]",
                    warning_summary_json="[]",
                    current_step=None,
                    progress_percentage=0,
                    started_at=None,
                    completed_at=None,
                    created_at=now,
                    updated_at=now,
                    duration_seconds=None,
                    execution_mode=request.execution_mode.value,
                    cancellation_requested=False,
                )
            )
            session.add_all(
                [
                    PipelineRunStepRow(
                        id=str(uuid4()),
                        pipeline_run_id=run_id,
                        step=step.value,
                        status=PipelineStepStatus.PENDING.value,
                        started_at=None,
                        completed_at=None,
                        duration_seconds=None,
                        warning_count=0,
                        error_count=0,
                        metadata_json="{}",
                    )
                    for step in PipelineStep
                ]
            )
        return self.get(run_id)

    def get(self, run_id: str) -> PipelineRun:
        with self._database.session() as session:
            row = session.get(PipelineRunRow, run_id)
        if row is None:
            raise PipelineRunNotFoundError("pipeline run was not found")
        return self._to_run(row)

    def list_runs(
        self,
        *,
        status: PipelineRunStatus | None = None,
        resume_id: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        limit: int = 50,
    ) -> list[PipelineRun]:
        statement = select(PipelineRunRow)
        if status is not None:
            statement = statement.where(PipelineRunRow.status == status.value)
        if resume_id is not None:
            statement = statement.where(PipelineRunRow.resume_id == resume_id)
        if created_after is not None:
            statement = statement.where(PipelineRunRow.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(PipelineRunRow.created_at <= created_before)
        statement = statement.order_by(PipelineRunRow.created_at.desc()).limit(limit)
        with self._database.session() as session:
            rows = list(session.scalars(statement))
        return [self._to_run(row) for row in rows]

    def list_steps(self, run_id: str) -> list[PipelineRunStepRecord]:
        self.get(run_id)
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(PipelineRunStepRow).where(
                        PipelineRunStepRow.pipeline_run_id == run_id
                    )
                )
            )
        order = {step.value: index for index, step in enumerate(PipelineStep)}
        return sorted((self._to_step(row) for row in rows), key=lambda item: order[item.step.value])

    def list_events(self, run_id: str, *, limit: int = 200) -> list[PipelineRunEvent]:
        self.get(run_id)
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(PipelineRunEventRow)
                    .where(PipelineRunEventRow.pipeline_run_id == run_id)
                    .order_by(PipelineRunEventRow.created_at.asc())
                    .limit(limit)
                )
            )
        return [self._to_event(row) for row in rows]

    def start_run(self, run_id: str) -> PipelineRun:
        now = datetime.now(UTC)
        with self._database.session() as session:
            row = self._require_run(session, run_id)
            if row.cancellation_requested:
                row.status = PipelineRunStatus.CANCELLED.value
                row.completed_at = now
            else:
                row.status = PipelineRunStatus.RUNNING.value
                row.started_at = now
            row.updated_at = now
        return self.get(run_id)

    def start_step(self, run_id: str, step: PipelineStep) -> PipelineRunStepRecord:
        now = datetime.now(UTC)
        with self._database.session() as session:
            run = self._require_run(session, run_id)
            row = self._require_step(session, run_id, step)
            row.status = PipelineStepStatus.RUNNING.value
            row.started_at = now
            run.current_step = step.value
            run.updated_at = now
        return self._get_step(run_id, step)

    def finish_step(
        self,
        run_id: str,
        step: PipelineStep,
        status: PipelineStepStatus,
        *,
        metadata: dict[str, object] | None = None,
        warning_count: int = 0,
        error_count: int = 0,
    ) -> PipelineRunStepRecord:
        now = datetime.now(UTC)
        with self._database.session() as session:
            run = self._require_run(session, run_id)
            row = self._require_step(session, run_id, step)
            row.status = status.value
            row.completed_at = now
            row.duration_seconds = self._elapsed_seconds(now, row.started_at)
            row.warning_count = warning_count
            row.error_count = error_count
            row.metadata_json = json.dumps(metadata or {}, sort_keys=True)
            run.updated_at = now
        return self._get_step(run_id, step)

    def update_progress(self, run_id: str, percentage: int) -> PipelineRun:
        with self._database.session() as session:
            row = self._require_run(session, run_id)
            row.progress_percentage = min(100, max(0, percentage))
            row.updated_at = datetime.now(UTC)
        return self.get(run_id)

    def add_warning(self, run_id: str, warning: str) -> PipelineRun:
        return self._append_summary(run_id, warning, warning=True)

    def add_error(self, run_id: str, error: str) -> PipelineRun:
        return self._append_summary(run_id, error, warning=False)

    def finish_run(
        self,
        run_id: str,
        status: PipelineRunStatus,
        result: PipelineRunResult | None,
    ) -> PipelineRun:
        if status not in {
            PipelineRunStatus.COMPLETED,
            PipelineRunStatus.PARTIAL_SUCCESS,
            PipelineRunStatus.FAILED,
            PipelineRunStatus.CANCELLED,
        }:
            raise PipelineRunStateError("pipeline run cannot finish with this status")
        now = datetime.now(UTC)
        with self._database.session() as session:
            row = self._require_run(session, run_id)
            row.status = status.value
            row.result_json = serialize_model(result) if result is not None else None
            row.completed_at = now
            row.updated_at = now
            row.duration_seconds = self._elapsed_seconds(now, row.started_at)
            if status in {PipelineRunStatus.COMPLETED, PipelineRunStatus.PARTIAL_SUCCESS}:
                row.progress_percentage = 100
                row.current_step = PipelineStep.FINALIZE.value
        return self.get(run_id)

    def request_cancellation(self, run_id: str) -> PipelineRun:
        now = datetime.now(UTC)
        with self._database.session() as session:
            row = self._require_run(session, run_id)
            status = PipelineRunStatus(row.status)
            if status in {
                PipelineRunStatus.COMPLETED,
                PipelineRunStatus.PARTIAL_SUCCESS,
                PipelineRunStatus.FAILED,
                PipelineRunStatus.CANCELLED,
            }:
                raise PipelineRunStateError("completed pipeline run cannot be cancelled")
            row.cancellation_requested = True
            if status is PipelineRunStatus.PENDING:
                row.status = PipelineRunStatus.CANCELLED.value
                row.completed_at = now
                row.duration_seconds = 0.0
            else:
                row.status = PipelineRunStatus.CANCEL_REQUESTED.value
            row.updated_at = now
        return self.get(run_id)

    def add_event(
        self,
        run_id: str,
        event_type: PipelineEventType,
        message: str,
        *,
        step: PipelineStep | None = None,
        metadata: dict[str, object] | None = None,
    ) -> PipelineRunEvent:
        self.get(run_id)
        row = PipelineRunEventRow(
            id=str(uuid4()),
            pipeline_run_id=run_id,
            event_type=event_type.value,
            step=step.value if step else None,
            message=message,
            metadata_json=json.dumps(metadata or {}, sort_keys=True),
            created_at=datetime.now(UTC),
        )
        with self._database.session() as session:
            session.add(row)
        return self._to_event(row)

    def _append_summary(self, run_id: str, message: str, *, warning: bool) -> PipelineRun:
        with self._database.session() as session:
            row = self._require_run(session, run_id)
            attribute = "warning_summary_json" if warning else "error_summary_json"
            values = self._load_json_list(getattr(row, attribute))
            values.append(message)
            setattr(row, attribute, json.dumps(values))
            row.updated_at = datetime.now(UTC)
        return self.get(run_id)

    def _get_step(self, run_id: str, step: PipelineStep) -> PipelineRunStepRecord:
        with self._database.session() as session:
            row = self._require_step(session, run_id, step)
        return self._to_step(row)

    @staticmethod
    def _require_run(session: Session, run_id: str) -> PipelineRunRow:
        row = session.get(PipelineRunRow, run_id)
        if row is None:
            raise PipelineRunNotFoundError("pipeline run was not found")
        return row

    @staticmethod
    def _require_step(session: Session, run_id: str, step: PipelineStep) -> PipelineRunStepRow:
        row = session.scalar(
            select(PipelineRunStepRow).where(
                PipelineRunStepRow.pipeline_run_id == run_id,
                PipelineRunStepRow.step == step.value,
            )
        )
        if row is None:
            raise PipelineRunNotFoundError("pipeline run step was not found")
        return row

    def _to_run(self, row: PipelineRunRow) -> PipelineRun:
        try:
            return PipelineRun(
                id=row.id,
                resume_id=row.resume_id,
                status=PipelineRunStatus(row.status),
                request=deserialize_model(row.request_json, PipelineRunRequest),
                result=(
                    deserialize_model(row.result_json, PipelineRunResult)
                    if row.result_json
                    else None
                ),
                errors=self._load_json_list(row.error_summary_json),
                warnings=self._load_json_list(row.warning_summary_json),
                current_step=PipelineStep(row.current_step) if row.current_step else None,
                progress_percentage=row.progress_percentage,
                started_at=row.started_at,
                completed_at=row.completed_at,
                created_at=row.created_at,
                updated_at=row.updated_at,
                duration_seconds=row.duration_seconds,
                execution_mode=row.execution_mode,
                cancellation_requested=row.cancellation_requested,
            )
        except (ArtifactSerializationError, ValueError) as exc:
            raise CorruptedArtifactError("stored pipeline run data is corrupted") from exc

    def _to_step(self, row: PipelineRunStepRow) -> PipelineRunStepRecord:
        try:
            return PipelineRunStepRecord(
                id=row.id,
                pipeline_run_id=row.pipeline_run_id,
                step=PipelineStep(row.step),
                status=PipelineStepStatus(row.status),
                started_at=row.started_at,
                completed_at=row.completed_at,
                duration_seconds=row.duration_seconds,
                warning_count=row.warning_count,
                error_count=row.error_count,
                metadata=json.loads(row.metadata_json),
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise CorruptedArtifactError("stored pipeline step data is corrupted") from exc

    def _to_event(self, row: PipelineRunEventRow) -> PipelineRunEvent:
        try:
            return PipelineRunEvent(
                id=row.id,
                pipeline_run_id=row.pipeline_run_id,
                event_type=PipelineEventType(row.event_type),
                step=PipelineStep(row.step) if row.step else None,
                message=row.message,
                metadata=json.loads(row.metadata_json),
                created_at=row.created_at,
            )
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise CorruptedArtifactError("stored pipeline event data is corrupted") from exc

    @staticmethod
    def _load_json_list(payload: str) -> list[str]:
        try:
            values = json.loads(payload)
            if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
                raise ValueError
            return values
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise CorruptedArtifactError("stored pipeline summary data is corrupted") from exc

    @staticmethod
    def _elapsed_seconds(end: datetime, start: datetime | None) -> float:
        if start is None:
            return 0.0
        comparable_end = end.replace(tzinfo=None) if start.tzinfo is None else end
        return max(0.0, (comparable_end - start).total_seconds())
