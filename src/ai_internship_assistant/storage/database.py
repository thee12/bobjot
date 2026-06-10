"""SQLAlchemy database foundation for versioned resume artifacts."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class DatabaseUnavailableError(RuntimeError):
    """Raised when the configured persistence database cannot be used."""


class Base(DeclarativeBase):
    """Declarative base for migration-friendly persistence tables."""


class MasterResumeRow(Base):
    """SQL row for a source-of-truth parsed master resume."""

    __tablename__ = "master_resumes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_name: Mapped[str | None] = mapped_column(String(255))
    resume_type: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    parsed_resume_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_text_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
    )
    source_file_metadata_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_master: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    model_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)


class ResumeVersionRow(Base):
    """SQL row for one immutable optimized resume version."""

    __tablename__ = "resume_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    master_resume_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("master_resumes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_name: Mapped[str] = mapped_column(String(512), nullable=False)
    target_job_id: Mapped[str | None] = mapped_column(
        String(255),
        ForeignKey("jobs.id", ondelete="SET NULL"),
        index=True,
    )
    target_job_title: Mapped[str | None] = mapped_column(String(512))
    target_company: Mapped[str | None] = mapped_column(String(512))
    optimized_resume_json: Mapped[str] = mapped_column(Text, nullable=False)
    optimization_plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    skill_gap_report_json: Mapped[str] = mapped_column(Text, nullable=False)
    ats_match_report_json: Mapped[str] = mapped_column(Text, nullable=False)
    safety_report_json: Mapped[str] = mapped_column(Text, nullable=False)
    change_log_json: Mapped[str] = mapped_column(Text, nullable=False)
    before_ats_score: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_after_score_low: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_after_score_high: Mapped[float] = mapped_column(Float, nullable=False)
    optimization_priority: Mapped[str] = mapped_column(String(32), nullable=False)
    optimized_content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    optimizer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    notes_json: Mapped[str] = mapped_column(Text, nullable=False)
    model_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)


class JobRow(Base):
    """SQL row for the minimal persisted job linkage contract."""

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    job_posting_json: Mapped[str] = mapped_column(Text, nullable=False)
    job_analysis_json: Mapped[str | None] = mapped_column(Text)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_schema_version: Mapped[str] = mapped_column(String(16), nullable=False)


class SavedJobRow(Base):
    """SQL row for a user-saved job snapshot and optional analysis artifacts."""

    __tablename__ = "saved_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_posting_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str] = mapped_column(String(512), nullable=False)
    location: Mapped[str | None] = mapped_column(String(512))
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    apply_url: Mapped[str | None] = mapped_column(Text)
    normalized_source_url: Mapped[str | None] = mapped_column(Text, index=True)
    normalized_apply_url: Mapped[str | None] = mapped_column(Text, index=True)
    normalized_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    job_posting_json: Mapped[str] = mapped_column(Text, nullable=False)
    job_analysis_json: Mapped[str | None] = mapped_column(Text)
    ats_match_report_json: Mapped[str | None] = mapped_column(Text)
    fit_score: Mapped[float | None] = mapped_column(Float)
    ats_score: Mapped[float | None] = mapped_column(Float)
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


class JobApplicationRow(Base):
    """SQL row for one application pipeline record."""

    __tablename__ = "job_applications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    saved_job_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("saved_jobs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    resume_version_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("resume_versions.id", ondelete="SET NULL"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    follow_up_date: Mapped[date | None] = mapped_column(Date, index=True)
    interview_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    response_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class ApplicationNoteRow(Base):
    """SQL row for an append-only application note."""

    __tablename__ = "application_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    note_type: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )


class ApplicationStatusHistoryRow(Base):
    """SQL row for one application status transition."""

    __tablename__ = "application_status_history"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("job_applications.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    old_status: Mapped[str | None] = mapped_column(String(32))
    new_status: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)


class PipelineRunRow(Base):
    """SQL row for one trackable pipeline execution."""

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    resume_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text)
    error_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    warning_summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    current_step: Mapped[str | None] = mapped_column(String(64))
    progress_percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    execution_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    cancellation_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PipelineRunStepRow(Base):
    """SQL row for one canonical pipeline step."""

    __tablename__ = "pipeline_run_steps"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pipeline_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)


class PipelineRunEventRow(Base):
    """SQL row for a privacy-safe pipeline timeline event."""

    __tablename__ = "pipeline_run_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pipeline_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pipeline_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    step: Mapped[str | None] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class Database:
    """Own the SQLAlchemy engine, session factory, and schema initialization."""

    def __init__(self, url: str) -> None:
        """Create a database adapter without exposing SQLAlchemy to services."""

        engine_options: dict[str, object] = {"future": True}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options.update(
                {
                    "connect_args": {"check_same_thread": False},
                    "poolclass": StaticPool,
                }
            )
        elif url.startswith("sqlite:"):
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(url, **engine_options)
        if url.startswith("sqlite:"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)
        self._sessions = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self) -> None:
        """Create Phase 5D tables; future migrations can replace this entrypoint."""

        try:
            Base.metadata.create_all(self.engine)
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError("database schema initialization failed") from exc

    @contextmanager
    def session(self) -> Iterator[Session]:
        """Provide one transactional session with rollback on expected database errors."""

        session = self._sessions()
        try:
            yield session
            session.commit()
        except SQLAlchemyError as exc:
            session.rollback()
            raise DatabaseUnavailableError("database operation failed") from exc
        finally:
            session.close()

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
