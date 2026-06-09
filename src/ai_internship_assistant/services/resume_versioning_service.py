"""Application service for immutable resume artifact versioning."""

from collections import Counter

from ai_internship_assistant.domain.models import (
    OptimizedResumeResult,
    Resume,
    ResumeSourceFileMetadata,
    ResumeVersionComparison,
    ResumeVersionSummary,
    StoredResume,
    StoredResumeVersion,
)
from ai_internship_assistant.storage.repositories import (
    JobRepository,
    MasterResumeNotFoundError,
    MasterResumeRepository,
    ResumeVersionRepository,
)
from ai_internship_assistant.storage.serialization import (
    normalized_text_hash,
    structured_content_hash,
)


class InvalidResumeVersionRelationshipError(ValueError):
    """Raised when a version references a master resume or job that is not stored."""


class ResumeVersioningService:
    """Store master resumes and immutable optimized variants with complete traceability."""

    def __init__(
        self,
        masters: MasterResumeRepository,
        versions: ResumeVersionRepository,
        jobs: JobRepository,
    ) -> None:
        self._masters = masters
        self._versions = versions
        self._jobs = jobs

    def save_master_resume(
        self,
        resume: Resume,
        source_file_metadata: ResumeSourceFileMetadata | None = None,
        *,
        source_text: str | None = None,
    ) -> StoredResume:
        """Save a new master resume without storing raw uploaded file bytes."""

        source_hash = (
            normalized_text_hash(source_text)
            if source_text is not None
            else structured_content_hash(resume)
        )
        return self._masters.create(resume, source_hash, source_file_metadata)

    def save_optimized_resume(
        self,
        master_resume_id: str,
        optimized_result: OptimizedResumeResult,
        target_job_id: str | None = None,
        *,
        notes: list[str] | None = None,
    ) -> StoredResumeVersion:
        """Create a new immutable optimized version; existing versions are never overwritten."""

        if not self._masters.exists(master_resume_id):
            raise MasterResumeNotFoundError("master resume was not found")
        if target_job_id is not None and not self._jobs.exists(target_job_id):
            raise InvalidResumeVersionRelationshipError("target job must be stored before linking")
        plan = optimized_result.optimization_plan
        version_name = self._unique_version_name(
            master_resume_id,
            optimized_result.optimized_resume.target_job_title,
            optimized_result.optimized_resume.target_company,
        )
        return self._versions.create(
            master_resume_id=master_resume_id,
            version_name=version_name,
            target_job_id=target_job_id,
            optimized_resume=optimized_result.optimized_resume,
            optimization_plan=plan,
            skill_gap_report=optimized_result.skill_gap_report,
            ats_match_report=optimized_result.ats_match_report,
            safety_report=optimized_result.safety_report,
            change_log=optimized_result.changes,
            before_ats_score=optimized_result.before_ats_score,
            estimated_after_score_low=optimized_result.estimated_after_ats_score.low,
            estimated_after_score_high=optimized_result.estimated_after_ats_score.high,
            optimization_priority=plan.optimization_priority,
            optimizer_version=optimized_result.optimizer_version,
            notes=notes or [],
        )

    def get_master_resume(self, master_resume_id: str) -> StoredResume:
        """Return one stored master resume."""

        return self._masters.get(master_resume_id)

    def list_master_resumes(self) -> list[StoredResume]:
        """Return all stored master resumes."""

        return self._masters.list_all()

    def get_resume_version(self, version_id: str) -> StoredResumeVersion:
        """Return one complete optimized resume version."""

        return self._versions.get(version_id)

    def list_versions_for_master_resume(
        self,
        master_resume_id: str,
    ) -> list[StoredResumeVersion]:
        """Return every optimized version linked to one master resume."""

        if not self._masters.exists(master_resume_id):
            raise MasterResumeNotFoundError("master resume was not found")
        return self._versions.list_for_master(master_resume_id)

    def list_versions_for_job(self, job_id: str) -> list[StoredResumeVersion]:
        """Return every optimized version linked to one stored job."""

        return self._versions.list_for_job(job_id)

    def get_latest_version_for_job(self, job_id: str) -> StoredResumeVersion | None:
        """Return the latest optimized version for one job."""

        return self._versions.latest_for_job(job_id)

    def get_version_summaries(self, master_resume_id: str) -> list[ResumeVersionSummary]:
        """Return lightweight version metadata without full resume JSON."""

        if not self._masters.exists(master_resume_id):
            raise MasterResumeNotFoundError("master resume was not found")
        return self._versions.list_summaries(master_resume_id)

    def update_version_notes(self, version_id: str, notes: list[str]) -> StoredResumeVersion:
        """Update mutable metadata notes while preserving immutable resume content."""

        return self._versions.update_notes(version_id, notes)

    def _unique_version_name(
        self,
        master_resume_id: str,
        job_title: str | None,
        company: str | None,
    ) -> str:
        title = job_title or "Optimized Resume"
        base = f"{title} - {company}" if company else f"{title} - Version 1"
        if not self._versions.version_name_exists(master_resume_id, base):
            return base
        version = 2
        while self._versions.version_name_exists(master_resume_id, f"{base} v{version}"):
            version += 1
        return f"{base} v{version}"


class ResumeVersionComparisonService:
    """Provide a lightweight comparison contract without rendering or content diffs."""

    def __init__(self, versions: ResumeVersionRepository) -> None:
        self._versions = versions

    def compare_versions(
        self,
        version_a_id: str,
        version_b_id: str,
    ) -> ResumeVersionComparison:
        """Compare score estimates and change-type counts for two stored versions."""

        version_a = self._versions.get(version_a_id)
        version_b = self._versions.get(version_b_id)
        return ResumeVersionComparison(
            version_a=self._summary(version_a),
            version_b=self._summary(version_b),
            score_estimate_delta_low=round(
                version_b.estimated_after_score_low - version_a.estimated_after_score_low,
                2,
            ),
            score_estimate_delta_high=round(
                version_b.estimated_after_score_high - version_a.estimated_after_score_high,
                2,
            ),
            change_type_counts_a=dict(
                Counter(change.change_type.value for change in version_a.change_log)
            ),
            change_type_counts_b=dict(
                Counter(change.change_type.value for change in version_b.change_log)
            ),
            warnings=["Comparison is metadata-only; semantic content diffing is future work."],
        )

    def _summary(self, version: StoredResumeVersion) -> ResumeVersionSummary:
        return ResumeVersionSummary(
            id=version.id,
            version_name=version.version_name,
            target_job_title=version.target_job_title,
            target_company=version.target_company,
            before_ats_score=version.before_ats_score,
            estimated_after_score_low=version.estimated_after_score_low,
            estimated_after_score_high=version.estimated_after_score_high,
            optimization_priority=version.optimization_priority,
            created_at=version.created_at,
        )
