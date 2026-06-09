"""Repositories for saved jobs and application pipeline records."""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import Select, and_, func, or_, select

from ai_internship_assistant.domain.models import (
    ApplicationFilters,
    ApplicationNote,
    ApplicationNoteType,
    ApplicationStatus,
    ApplicationStatusHistory,
    ATSMatchReport,
    JobAnalysis,
    JobApplication,
    JobApplicationSummary,
    JobPosting,
    SavedJob,
    SavedJobStatus,
)
from ai_internship_assistant.services.job_normalization import JobNormalizationService
from ai_internship_assistant.storage.database import (
    ApplicationNoteRow,
    ApplicationStatusHistoryRow,
    Database,
    JobApplicationRow,
    SavedJobRow,
)
from ai_internship_assistant.storage.repositories import CorruptedArtifactError, PersistenceError
from ai_internship_assistant.storage.serialization import (
    ArtifactSerializationError,
    deserialize_model,
    serialize_model,
)


class SavedJobNotFoundError(PersistenceError):
    """Raised when a requested saved job does not exist."""


class ApplicationNotFoundError(PersistenceError):
    """Raised when a requested application does not exist."""


class SavedJobRepository:
    """Persist deduplicated job snapshots and optional analysis artifacts."""

    def __init__(
        self,
        database: Database,
        normalizer: JobNormalizationService | None = None,
    ) -> None:
        self._database = database
        self._normalizer = normalizer or JobNormalizationService()

    def save(
        self,
        job: JobPosting,
        *,
        job_analysis: JobAnalysis | None = None,
        ats_match_report: ATSMatchReport | None = None,
        fit_score: float | None = None,
        notes: str | None = None,
        allow_duplicate: bool = False,
    ) -> SavedJob:
        """Create a saved job or refresh the last-seen time for a duplicate."""

        normalized = self._normalizer.normalize(job)
        now = datetime.now(UTC)
        with self._database.session() as session:
            existing = None
            if not allow_duplicate:
                conditions = [
                    SavedJobRow.job_posting_id == job.id,
                    SavedJobRow.normalized_fingerprint == normalized.fingerprint,
                ]
                if normalized.normalized_apply_url:
                    conditions.append(
                        SavedJobRow.normalized_apply_url == normalized.normalized_apply_url
                    )
                if normalized.normalized_source_url:
                    conditions.append(
                        SavedJobRow.normalized_source_url == normalized.normalized_source_url
                    )
                existing = session.scalar(select(SavedJobRow).where(or_(*conditions)).limit(1))
            if existing is not None:
                existing.last_seen_at = now
                if existing.job_posting_id == job.id:
                    existing.job_posting_json = serialize_model(job)
                    if job_analysis is not None:
                        existing.job_analysis_json = serialize_model(job_analysis)
                    if ats_match_report is not None:
                        existing.ats_match_report_json = serialize_model(ats_match_report)
                        existing.ats_score = ats_match_report.overall_score
                    if fit_score is not None:
                        existing.fit_score = fit_score
                if notes is not None:
                    existing.notes = notes
                saved_job_id = existing.id
            else:
                row = SavedJobRow(
                    id=str(uuid4()),
                    job_posting_id=job.id,
                    title=job.title,
                    company=job.company,
                    location=job.location,
                    source=job.source.value,
                    source_url=str(job.source_url) if job.source_url else None,
                    apply_url=str(job.apply_url) if job.apply_url else None,
                    normalized_source_url=normalized.normalized_source_url,
                    normalized_apply_url=normalized.normalized_apply_url,
                    normalized_fingerprint=normalized.fingerprint,
                    job_posting_json=serialize_model(job),
                    job_analysis_json=serialize_model(job_analysis) if job_analysis else None,
                    ats_match_report_json=(
                        serialize_model(ats_match_report) if ats_match_report else None
                    ),
                    fit_score=fit_score,
                    ats_score=ats_match_report.overall_score if ats_match_report else None,
                    saved_at=now,
                    last_seen_at=now,
                    status=SavedJobStatus.ACTIVE.value,
                    is_active=True,
                    notes=notes,
                )
                session.add(row)
                saved_job_id = row.id
        return self.get(saved_job_id)

    def get(self, saved_job_id: str) -> SavedJob:
        """Return one typed saved-job snapshot."""

        with self._database.session() as session:
            row = session.get(SavedJobRow, saved_job_id)
        if row is None:
            raise SavedJobNotFoundError("saved job was not found")
        return self._to_model(row)

    def exists(self, saved_job_id: str) -> bool:
        """Return whether a saved job exists without loading its JSON."""

        with self._database.session() as session:
            return session.get(SavedJobRow, saved_job_id) is not None

    def list_all(
        self,
        *,
        company: str | None = None,
        source: str | None = None,
        active_only: bool = False,
        limit: int | None = None,
    ) -> list[SavedJob]:
        """Return saved jobs newest first with lightweight database filtering."""

        statement = select(SavedJobRow)
        conditions = []
        if company:
            conditions.append(SavedJobRow.company.ilike(f"%{company.strip()}%"))
        if source:
            conditions.append(SavedJobRow.source.ilike(f"%{source.strip()}%"))
        if active_only:
            conditions.append(SavedJobRow.is_active.is_(True))
        statement = statement.where(*conditions).order_by(SavedJobRow.saved_at.desc())
        if limit is not None:
            statement = statement.limit(limit)
        with self._database.session() as session:
            rows = list(session.scalars(statement))
        return [self._to_model(row) for row in rows]

    def archive(self, saved_job_id: str) -> SavedJob:
        """Archive a saved job without deleting its application relationships."""

        with self._database.session() as session:
            row = session.get(SavedJobRow, saved_job_id)
            if row is None:
                raise SavedJobNotFoundError("saved job was not found")
            row.status = SavedJobStatus.ARCHIVED.value
            row.is_active = False
        return self.get(saved_job_id)

    def _to_model(self, row: SavedJobRow) -> SavedJob:
        try:
            return SavedJob(
                id=row.id,
                job_posting_id=row.job_posting_id,
                title=row.title,
                company=row.company,
                location=row.location,
                source=row.source,
                source_url=row.source_url,
                apply_url=row.apply_url,
                job_posting=deserialize_model(row.job_posting_json, JobPosting),
                job_analysis=(
                    deserialize_model(row.job_analysis_json, JobAnalysis)
                    if row.job_analysis_json
                    else None
                ),
                ats_match_report=(
                    deserialize_model(row.ats_match_report_json, ATSMatchReport)
                    if row.ats_match_report_json
                    else None
                ),
                fit_score=row.fit_score,
                ats_score=row.ats_score,
                saved_at=row.saved_at,
                last_seen_at=row.last_seen_at,
                status=SavedJobStatus(row.status),
                is_active=row.is_active,
                notes=row.notes,
            )
        except (ArtifactSerializationError, ValueError) as exc:
            raise CorruptedArtifactError("stored saved job data is corrupted") from exc


class ApplicationRepository:
    """Persist applications, append-only notes, status history, and list projections."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        saved_job_id: str,
        *,
        resume_version_id: str | None,
        status: ApplicationStatus,
        source: str | None,
        notes: str | None,
        follow_up_date: date | None,
    ) -> JobApplication:
        """Create one application and its initial status-history record."""

        now = datetime.now(UTC)
        row = JobApplicationRow(
            id=str(uuid4()),
            saved_job_id=saved_job_id,
            resume_version_id=resume_version_id,
            status=status.value,
            applied_at=now if status is ApplicationStatus.APPLIED else None,
            follow_up_date=follow_up_date,
            response_received_at=(
                now
                if status
                in {
                    ApplicationStatus.INTERVIEWING,
                    ApplicationStatus.TECHNICAL_INTERVIEW,
                    ApplicationStatus.FINAL_INTERVIEW,
                }
                else None
            ),
            rejected_at=now if status is ApplicationStatus.REJECTED else None,
            offer_received_at=now if status is ApplicationStatus.OFFER else None,
            withdrawn_at=now if status is ApplicationStatus.WITHDRAWN else None,
            source=source,
            notes=notes,
            created_at=now,
            updated_at=now,
        )
        history = ApplicationStatusHistoryRow(
            id=str(uuid4()),
            application_id=row.id,
            old_status=None,
            new_status=status.value,
            sequence_number=1,
            changed_at=now,
            note="Application created.",
        )
        with self._database.session() as session:
            session.add(row)
            session.flush()
            session.add(history)
        return self.get(row.id)

    def get(self, application_id: str) -> JobApplication:
        """Return one typed application record."""

        with self._database.session() as session:
            row = session.get(JobApplicationRow, application_id)
        if row is None:
            raise ApplicationNotFoundError("application was not found")
        return self._to_model(row)

    def update_status(
        self,
        application_id: str,
        new_status: ApplicationStatus,
        *,
        note: str | None = None,
        changed_at: datetime | None = None,
    ) -> JobApplication:
        """Update status and event timestamps atomically while preserving old timestamps."""

        timestamp = changed_at or datetime.now(UTC)
        with self._database.session() as session:
            row = session.get(JobApplicationRow, application_id)
            if row is None:
                raise ApplicationNotFoundError("application was not found")
            old_status = row.status
            row.status = new_status.value
            row.updated_at = timestamp
            if new_status is ApplicationStatus.APPLIED and row.applied_at is None:
                row.applied_at = timestamp
            if new_status in {
                ApplicationStatus.INTERVIEWING,
                ApplicationStatus.TECHNICAL_INTERVIEW,
                ApplicationStatus.FINAL_INTERVIEW,
            } and row.response_received_at is None:
                row.response_received_at = timestamp
            if new_status is ApplicationStatus.REJECTED and row.rejected_at is None:
                row.rejected_at = timestamp
            if new_status is ApplicationStatus.OFFER and row.offer_received_at is None:
                row.offer_received_at = timestamp
            if new_status is ApplicationStatus.WITHDRAWN and row.withdrawn_at is None:
                row.withdrawn_at = timestamp
            sequence_number = (
                session.scalar(
                    select(func.max(ApplicationStatusHistoryRow.sequence_number)).where(
                        ApplicationStatusHistoryRow.application_id == application_id
                    )
                )
                or 0
            ) + 1
            session.add(
                ApplicationStatusHistoryRow(
                    id=str(uuid4()),
                    application_id=application_id,
                    old_status=old_status,
                    new_status=new_status.value,
                    sequence_number=sequence_number,
                    changed_at=timestamp,
                    note=note,
                )
            )
        return self.get(application_id)

    def set_follow_up_date(
        self,
        application_id: str,
        follow_up_date: date | None,
    ) -> JobApplication:
        """Set or clear a follow-up date."""

        with self._database.session() as session:
            row = session.get(JobApplicationRow, application_id)
            if row is None:
                raise ApplicationNotFoundError("application was not found")
            row.follow_up_date = follow_up_date
            row.updated_at = datetime.now(UTC)
        return self.get(application_id)

    def set_interview_date(
        self,
        application_id: str,
        interview_date: datetime | None,
    ) -> JobApplication:
        """Set or clear a scheduled interview date."""

        with self._database.session() as session:
            row = session.get(JobApplicationRow, application_id)
            if row is None:
                raise ApplicationNotFoundError("application was not found")
            row.interview_date = interview_date
            row.updated_at = datetime.now(UTC)
        return self.get(application_id)

    def link_resume_version(
        self,
        application_id: str,
        resume_version_id: str | None,
    ) -> JobApplication:
        """Link or unlink a persisted resume version from an application."""

        with self._database.session() as session:
            row = session.get(JobApplicationRow, application_id)
            if row is None:
                raise ApplicationNotFoundError("application was not found")
            row.resume_version_id = resume_version_id
            row.updated_at = datetime.now(UTC)
        return self.get(application_id)

    def add_note(
        self,
        application_id: str,
        note: str,
        note_type: ApplicationNoteType,
    ) -> ApplicationNote:
        """Append one note without changing existing notes."""

        now = datetime.now(UTC)
        with self._database.session() as session:
            if session.get(JobApplicationRow, application_id) is None:
                raise ApplicationNotFoundError("application was not found")
            sequence_number = (
                session.scalar(
                    select(func.max(ApplicationNoteRow.sequence_number)).where(
                        ApplicationNoteRow.application_id == application_id
                    )
                )
                or 0
            ) + 1
            row = ApplicationNoteRow(
                id=str(uuid4()),
                application_id=application_id,
                note=note,
                note_type=note_type.value,
                sequence_number=sequence_number,
                created_at=now,
            )
            session.add(row)
        return self._note_to_model(row)

    def list_notes(self, application_id: str) -> list[ApplicationNote]:
        """Return append-only notes newest first."""

        self._require_application(application_id)
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(ApplicationNoteRow)
                    .where(ApplicationNoteRow.application_id == application_id)
                    .order_by(ApplicationNoteRow.sequence_number.desc())
                )
            )
        return [self._note_to_model(row) for row in rows]

    def list_status_history(self, application_id: str) -> list[ApplicationStatusHistory]:
        """Return status changes in chronological order."""

        self._require_application(application_id)
        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(ApplicationStatusHistoryRow)
                    .where(ApplicationStatusHistoryRow.application_id == application_id)
                    .order_by(ApplicationStatusHistoryRow.sequence_number.asc())
                )
            )
        return [self._history_to_model(row) for row in rows]

    def list_summaries(
        self,
        filters: ApplicationFilters | None = None,
    ) -> list[JobApplicationSummary]:
        """Return filtered lightweight application summaries."""

        resolved = filters or ApplicationFilters()
        statement = self._filtered_statement(resolved)
        with self._database.session() as session:
            rows = list(session.execute(statement).all())
            summaries: list[JobApplicationSummary] = []
            for application, saved_job in rows:
                latest_note = session.scalar(
                    select(ApplicationNoteRow.note)
                    .where(ApplicationNoteRow.application_id == application.id)
                    .order_by(ApplicationNoteRow.sequence_number.desc())
                    .limit(1)
                )
                summaries.append(self._summary(application, saved_job, latest_note))
        return summaries

    def get_summary(self, application_id: str) -> JobApplicationSummary:
        """Return one joined lightweight application summary."""

        with self._database.session() as session:
            row = session.execute(
                select(JobApplicationRow, SavedJobRow)
                .join(SavedJobRow, JobApplicationRow.saved_job_id == SavedJobRow.id)
                .where(JobApplicationRow.id == application_id)
            ).one_or_none()
            if row is None:
                raise ApplicationNotFoundError("application was not found")
            application, saved_job = row
            latest_note = session.scalar(
                select(ApplicationNoteRow.note)
                .where(ApplicationNoteRow.application_id == application_id)
                .order_by(ApplicationNoteRow.sequence_number.desc())
                .limit(1)
            )
        return self._summary(application, saved_job, latest_note)

    def _filtered_statement(
        self,
        filters: ApplicationFilters,
    ) -> Select[tuple[JobApplicationRow, SavedJobRow]]:
        statement = select(JobApplicationRow, SavedJobRow).join(
            SavedJobRow,
            JobApplicationRow.saved_job_id == SavedJobRow.id,
        )
        conditions = []
        if filters.status is not None:
            conditions.append(JobApplicationRow.status == filters.status.value)
        if filters.company:
            conditions.append(SavedJobRow.company.ilike(f"%{filters.company.strip()}%"))
        if filters.role_keyword:
            conditions.append(SavedJobRow.title.ilike(f"%{filters.role_keyword.strip()}%"))
        if filters.source:
            conditions.append(JobApplicationRow.source.ilike(f"%{filters.source.strip()}%"))
        if filters.applied_after:
            conditions.append(JobApplicationRow.applied_at >= filters.applied_after)
        if filters.applied_before:
            conditions.append(JobApplicationRow.applied_at <= filters.applied_before)
        if filters.needs_follow_up is not None:
            due = and_(
                JobApplicationRow.follow_up_date.is_not(None),
                JobApplicationRow.follow_up_date <= filters.as_of_date,
                JobApplicationRow.status.not_in(
                    [
                        ApplicationStatus.REJECTED.value,
                        ApplicationStatus.OFFER.value,
                        ApplicationStatus.CLOSED.value,
                        ApplicationStatus.WITHDRAWN.value,
                    ]
                ),
            )
            not_due = or_(
                JobApplicationRow.follow_up_date.is_(None),
                JobApplicationRow.follow_up_date > filters.as_of_date,
                JobApplicationRow.status.in_(
                    [
                        ApplicationStatus.REJECTED.value,
                        ApplicationStatus.OFFER.value,
                        ApplicationStatus.CLOSED.value,
                        ApplicationStatus.WITHDRAWN.value,
                    ]
                ),
            )
            conditions.append(due if filters.needs_follow_up else not_due)
        if filters.has_interview is not None:
            has_interview = or_(
                JobApplicationRow.interview_date.is_not(None),
                JobApplicationRow.status.in_(
                    [
                        ApplicationStatus.INTERVIEWING.value,
                        ApplicationStatus.TECHNICAL_INTERVIEW.value,
                        ApplicationStatus.FINAL_INTERVIEW.value,
                    ]
                ),
            )
            conditions.append(has_interview if filters.has_interview else ~has_interview)
        if filters.resume_version_id:
            conditions.append(JobApplicationRow.resume_version_id == filters.resume_version_id)
        return statement.where(*conditions).order_by(JobApplicationRow.updated_at.desc())

    def _require_application(self, application_id: str) -> None:
        with self._database.session() as session:
            exists = session.get(JobApplicationRow, application_id) is not None
        if not exists:
            raise ApplicationNotFoundError("application was not found")

    def _to_model(self, row: JobApplicationRow) -> JobApplication:
        try:
            return JobApplication(
                id=row.id,
                saved_job_id=row.saved_job_id,
                resume_version_id=row.resume_version_id,
                status=ApplicationStatus(row.status),
                applied_at=row.applied_at,
                follow_up_date=row.follow_up_date,
                interview_date=row.interview_date,
                response_received_at=row.response_received_at,
                rejected_at=row.rejected_at,
                offer_received_at=row.offer_received_at,
                withdrawn_at=row.withdrawn_at,
                source=row.source,
                notes=row.notes,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        except ValueError as exc:
            raise CorruptedArtifactError("stored application data is corrupted") from exc

    def _note_to_model(self, row: ApplicationNoteRow) -> ApplicationNote:
        try:
            return ApplicationNote(
                id=row.id,
                application_id=row.application_id,
                note=row.note,
                note_type=ApplicationNoteType(row.note_type),
                created_at=row.created_at,
            )
        except ValueError as exc:
            raise CorruptedArtifactError("stored application note data is corrupted") from exc

    def _history_to_model(self, row: ApplicationStatusHistoryRow) -> ApplicationStatusHistory:
        try:
            return ApplicationStatusHistory(
                id=row.id,
                application_id=row.application_id,
                old_status=ApplicationStatus(row.old_status) if row.old_status else None,
                new_status=ApplicationStatus(row.new_status),
                changed_at=row.changed_at,
                note=row.note,
            )
        except ValueError as exc:
            raise CorruptedArtifactError("stored application history data is corrupted") from exc

    def _summary(
        self,
        application: JobApplicationRow,
        saved_job: SavedJobRow,
        latest_note: str | None,
    ) -> JobApplicationSummary:
        try:
            return JobApplicationSummary(
                id=application.id,
                saved_job_id=saved_job.id,
                title=saved_job.title,
                company=saved_job.company,
                status=ApplicationStatus(application.status),
                applied_at=application.applied_at,
                follow_up_date=application.follow_up_date,
                resume_version_id=application.resume_version_id,
                ats_score=saved_job.ats_score,
                fit_score=saved_job.fit_score,
                latest_note=latest_note,
                updated_at=application.updated_at,
            )
        except ValueError as exc:
            raise CorruptedArtifactError("stored application summary data is corrupted") from exc
