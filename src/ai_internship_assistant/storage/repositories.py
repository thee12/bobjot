"""Typed repositories isolating SQLAlchemy persistence from application services."""

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Select, select

from ai_internship_assistant.domain.models import (
    ATSMatchReport,
    JobAnalysis,
    JobPosting,
    OptimizedResume,
    PlanPriority,
    Resume,
    ResumeChange,
    ResumeOptimizationPlan,
    ResumeOptimizationSafetyReport,
    ResumeSourceFileMetadata,
    ResumeType,
    ResumeVersionSummary,
    SkillGapReport,
    StoredJob,
    StoredResume,
    StoredResumeVersion,
)
from ai_internship_assistant.storage.database import (
    Database,
    JobRow,
    MasterResumeRow,
    ResumeVersionRow,
)
from ai_internship_assistant.storage.serialization import (
    ArtifactSerializationError,
    compatibility_warnings,
    deserialize_model,
    deserialize_models,
    model_schema_version,
    serialize_model,
    serialize_models,
    structured_content_hash,
)


class PersistenceError(RuntimeError):
    """Base class for meaningful persistence-layer failures."""


class MasterResumeNotFoundError(PersistenceError):
    """Raised when a requested master resume does not exist."""


class ResumeVersionNotFoundError(PersistenceError):
    """Raised when a requested optimized resume version does not exist."""


class JobNotFoundError(PersistenceError):
    """Raised when a requested persisted job does not exist."""


class DuplicateMasterResumeError(PersistenceError):
    """Raised when a source hash already belongs to a stored master resume."""


class CorruptedArtifactError(PersistenceError):
    """Raised when stored JSON cannot be reconstructed into its typed model."""


class MasterResumeRepository:
    """Persist and retrieve source-of-truth structured master resumes."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        resume: Resume,
        source_text_hash: str,
        source_file_metadata: ResumeSourceFileMetadata | None = None,
    ) -> StoredResume:
        """Create a master resume once; duplicate source hashes are rejected."""

        with self._database.session() as session:
            existing = session.scalar(
                select(MasterResumeRow).where(
                    MasterResumeRow.source_text_hash == source_text_hash
                )
            )
            if existing:
                raise DuplicateMasterResumeError("a master resume with this source already exists")
            now = datetime.now(UTC)
            row = MasterResumeRow(
                id=str(uuid4()),
                candidate_name=resume.full_name,
                resume_type=ResumeType.MASTER.value,
                original_filename=(
                    source_file_metadata.original_filename if source_file_metadata else None
                ),
                parsed_resume_json=serialize_model(resume),
                source_text_hash=source_text_hash,
                source_file_metadata_json=(
                    serialize_model(source_file_metadata) if source_file_metadata else None
                ),
                created_at=now,
                updated_at=now,
                is_master=True,
                model_schema_version=model_schema_version(),
            )
            session.add(row)
        return self._to_model(row)

    def get(self, resume_id: str) -> StoredResume:
        """Return one typed master resume."""

        with self._database.session() as session:
            row = session.get(MasterResumeRow, resume_id)
        if row is None:
            raise MasterResumeNotFoundError("master resume was not found")
        return self._to_model(row)

    def list_all(self) -> list[StoredResume]:
        """Return all master resumes ordered newest first."""

        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(MasterResumeRow).order_by(MasterResumeRow.created_at.desc())
                )
            )
        return [self._to_model(row) for row in rows]

    def exists(self, resume_id: str) -> bool:
        """Return whether a master resume exists without loading its JSON."""

        with self._database.session() as session:
            return session.get(MasterResumeRow, resume_id) is not None

    def _to_model(self, row: MasterResumeRow) -> StoredResume:
        try:
            metadata = (
                deserialize_model(row.source_file_metadata_json, ResumeSourceFileMetadata)
                if row.source_file_metadata_json
                else None
            )
            return StoredResume(
                id=row.id,
                candidate_name=row.candidate_name,
                resume_type=ResumeType(row.resume_type),
                original_filename=row.original_filename,
                parsed_resume=deserialize_model(row.parsed_resume_json, Resume),
                source_text_hash=row.source_text_hash,
                source_file_metadata=metadata,
                created_at=row.created_at,
                updated_at=row.updated_at,
                is_master=row.is_master,
                model_schema_version=row.model_schema_version,
                compatibility_warnings=compatibility_warnings(row.model_schema_version),
            )
        except (ArtifactSerializationError, ValueError) as exc:
            raise CorruptedArtifactError("stored master resume data is corrupted") from exc


class ResumeVersionRepository:
    """Persist immutable optimized versions and provide typed retrieval projections."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def create(
        self,
        *,
        master_resume_id: str,
        version_name: str,
        target_job_id: str | None,
        optimized_resume: OptimizedResume,
        optimization_plan: ResumeOptimizationPlan,
        skill_gap_report: SkillGapReport,
        ats_match_report: ATSMatchReport,
        safety_report: ResumeOptimizationSafetyReport,
        change_log: Sequence[ResumeChange],
        before_ats_score: float,
        estimated_after_score_low: float,
        estimated_after_score_high: float,
        optimization_priority: PlanPriority,
        optimizer_version: str,
        notes: Sequence[str],
    ) -> StoredResumeVersion:
        """Create one immutable optimized version."""

        row = ResumeVersionRow(
            id=str(uuid4()),
            master_resume_id=master_resume_id,
            version_name=version_name,
            target_job_id=target_job_id,
            target_job_title=optimized_resume.target_job_title,
            target_company=optimized_resume.target_company,
            optimized_resume_json=serialize_model(optimized_resume),
            optimization_plan_json=serialize_model(optimization_plan),
            skill_gap_report_json=serialize_model(skill_gap_report),
            ats_match_report_json=serialize_model(ats_match_report),
            safety_report_json=serialize_model(safety_report),
            change_log_json=serialize_models(list(change_log)),
            before_ats_score=before_ats_score,
            estimated_after_score_low=estimated_after_score_low,
            estimated_after_score_high=estimated_after_score_high,
            optimization_priority=optimization_priority.value,
            optimized_content_hash=structured_content_hash(optimized_resume),
            optimizer_version=optimizer_version,
            created_at=datetime.now(UTC),
            notes_json=json.dumps(list(notes)),
            model_schema_version=model_schema_version(),
        )
        with self._database.session() as session:
            session.add(row)
        return self._to_model(row)

    def get(self, version_id: str) -> StoredResumeVersion:
        """Return one complete typed optimized version."""

        with self._database.session() as session:
            row = session.get(ResumeVersionRow, version_id)
        if row is None:
            raise ResumeVersionNotFoundError("resume version was not found")
        return self._to_model(row)

    def exists(self, version_id: str) -> bool:
        """Return whether a resume version exists without loading sensitive JSON."""

        with self._database.session() as session:
            return session.get(ResumeVersionRow, version_id) is not None

    def list_for_master(self, master_resume_id: str) -> list[StoredResumeVersion]:
        """Return all versions for a master resume ordered newest first."""

        return self._query_versions(
            select(ResumeVersionRow)
            .where(ResumeVersionRow.master_resume_id == master_resume_id)
            .order_by(ResumeVersionRow.created_at.desc())
        )

    def list_for_job(self, job_id: str) -> list[StoredResumeVersion]:
        """Return all versions explicitly linked to a persisted job."""

        return self._query_versions(
            select(ResumeVersionRow)
            .where(ResumeVersionRow.target_job_id == job_id)
            .order_by(ResumeVersionRow.created_at.desc())
        )

    def latest_for_job(self, job_id: str) -> StoredResumeVersion | None:
        """Return the newest version for a job, if any."""

        with self._database.session() as session:
            row = session.scalar(
                select(ResumeVersionRow)
                .where(ResumeVersionRow.target_job_id == job_id)
                .order_by(ResumeVersionRow.created_at.desc())
                .limit(1)
            )
        return self._to_model(row) if row else None

    def list_summaries(self, master_resume_id: str) -> list[ResumeVersionSummary]:
        """Return lightweight summaries without deserializing sensitive resume content."""

        with self._database.session() as session:
            rows = list(
                session.scalars(
                    select(ResumeVersionRow)
                    .where(ResumeVersionRow.master_resume_id == master_resume_id)
                    .order_by(ResumeVersionRow.created_at.desc())
                )
            )
        return [
            ResumeVersionSummary(
                id=row.id,
                version_name=row.version_name,
                target_job_title=row.target_job_title,
                target_company=row.target_company,
                before_ats_score=row.before_ats_score,
                estimated_after_score_low=row.estimated_after_score_low,
                estimated_after_score_high=row.estimated_after_score_high,
                optimization_priority=PlanPriority(row.optimization_priority),
                created_at=row.created_at,
            )
            for row in rows
        ]

    def version_name_exists(self, master_resume_id: str, version_name: str) -> bool:
        """Return whether a master resume already uses the supplied version name."""

        with self._database.session() as session:
            row = session.scalar(
                select(ResumeVersionRow.id).where(
                    ResumeVersionRow.master_resume_id == master_resume_id,
                    ResumeVersionRow.version_name == version_name,
                )
            )
        return row is not None

    def update_notes(self, version_id: str, notes: Sequence[str]) -> StoredResumeVersion:
        """Update metadata notes without mutating immutable optimized content."""

        with self._database.session() as session:
            row = session.get(ResumeVersionRow, version_id)
            if row is None:
                raise ResumeVersionNotFoundError("resume version was not found")
            row.notes_json = json.dumps(list(notes))
        return self.get(version_id)

    def _query_versions(
        self,
        statement: Select[tuple[ResumeVersionRow]],
    ) -> list[StoredResumeVersion]:
        with self._database.session() as session:
            rows = list(session.scalars(statement))
        return [self._to_model(row) for row in rows]

    def _to_model(self, row: ResumeVersionRow) -> StoredResumeVersion:
        try:
            notes = json.loads(row.notes_json)
            if not isinstance(notes, list) or not all(isinstance(item, str) for item in notes):
                raise ValueError
            return StoredResumeVersion(
                id=row.id,
                master_resume_id=row.master_resume_id,
                version_name=row.version_name,
                target_job_id=row.target_job_id,
                target_job_title=row.target_job_title,
                target_company=row.target_company,
                optimized_resume=deserialize_model(row.optimized_resume_json, OptimizedResume),
                optimization_plan=deserialize_model(
                    row.optimization_plan_json,
                    ResumeOptimizationPlan,
                ),
                skill_gap_report=deserialize_model(row.skill_gap_report_json, SkillGapReport),
                ats_match_report=deserialize_model(row.ats_match_report_json, ATSMatchReport),
                safety_report=deserialize_model(
                    row.safety_report_json,
                    ResumeOptimizationSafetyReport,
                ),
                change_log=deserialize_models(row.change_log_json, ResumeChange),
                before_ats_score=row.before_ats_score,
                estimated_after_score_low=row.estimated_after_score_low,
                estimated_after_score_high=row.estimated_after_score_high,
                optimization_priority=PlanPriority(row.optimization_priority),
                optimized_content_hash=row.optimized_content_hash,
                created_at=row.created_at,
                optimizer_version=row.optimizer_version,
                notes=notes,
                model_schema_version=row.model_schema_version,
                compatibility_warnings=compatibility_warnings(row.model_schema_version),
            )
        except (ArtifactSerializationError, json.JSONDecodeError, ValueError) as exc:
            raise CorruptedArtifactError("stored resume version data is corrupted") from exc


class JobRepository:
    """Persist minimal jobs for explicit optimized-version linkage."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def save(self, posting: JobPosting, analysis: JobAnalysis | None = None) -> StoredJob:
        """Insert or replace job metadata and structured analysis."""

        now = datetime.now(UTC)
        row = JobRow(
            id=posting.id,
            title=posting.title,
            company=posting.company,
            location=posting.location,
            source=posting.source.value,
            source_url=str(posting.source_url) if posting.source_url else None,
            apply_url=str(posting.apply_url) if posting.apply_url else None,
            job_posting_json=serialize_model(posting),
            job_analysis_json=serialize_model(analysis) if analysis else None,
            discovered_at=posting.discovered_at,
            created_at=now,
            model_schema_version=model_schema_version(),
        )
        with self._database.session() as session:
            session.merge(row)
        return self.get(posting.id)

    def get(self, job_id: str) -> StoredJob:
        """Return one persisted job."""

        with self._database.session() as session:
            row = session.get(JobRow, job_id)
        if row is None:
            raise JobNotFoundError("job was not found")
        try:
            return StoredJob(
                id=row.id,
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
                discovered_at=row.discovered_at,
                created_at=row.created_at,
                model_schema_version=row.model_schema_version,
                compatibility_warnings=compatibility_warnings(row.model_schema_version),
            )
        except ArtifactSerializationError as exc:
            raise CorruptedArtifactError("stored job data is corrupted") from exc

    def exists(self, job_id: str) -> bool:
        """Return whether a job exists without deserializing its contents."""

        with self._database.session() as session:
            return session.get(JobRow, job_id) is not None
