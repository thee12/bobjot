"""Application service for saved jobs and job-application pipeline tracking."""

from datetime import date, datetime

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
)
from ai_internship_assistant.storage.application_repositories import (
    ApplicationRepository,
    SavedJobRepository,
)
from ai_internship_assistant.storage.repositories import (
    ResumeVersionNotFoundError,
    ResumeVersionRepository,
)


class ApplicationTrackingError(RuntimeError):
    """Base class for application-tracking service failures."""


class InvalidApplicationNoteError(ApplicationTrackingError):
    """Raised when an application note is empty."""


class ApplicationTrackingService:
    """Coordinate saved jobs, application records, resume linkage, and outcomes."""

    def __init__(
        self,
        saved_jobs: SavedJobRepository,
        applications: ApplicationRepository,
        resume_versions: ResumeVersionRepository,
    ) -> None:
        self._saved_jobs = saved_jobs
        self._applications = applications
        self._resume_versions = resume_versions

    def save_job(
        self,
        job: JobPosting,
        job_analysis: JobAnalysis | None = None,
        ats_match_report: ATSMatchReport | None = None,
        *,
        fit_score: float | None = None,
        notes: str | None = None,
        allow_duplicate: bool = False,
    ) -> SavedJob:
        """Save a job snapshot or refresh an existing normalized duplicate."""

        return self._saved_jobs.save(
            job,
            job_analysis=job_analysis,
            ats_match_report=ats_match_report,
            fit_score=fit_score,
            notes=notes,
            allow_duplicate=allow_duplicate,
        )

    def create_application(
        self,
        saved_job_id: str,
        resume_version_id: str | None = None,
        status: ApplicationStatus = ApplicationStatus.PLANNED,
        *,
        source: str | None = None,
        notes: str | None = None,
        follow_up_date: date | None = None,
    ) -> JobApplication:
        """Create an application without implicitly marking it as applied."""

        saved_job = self._saved_jobs.get(saved_job_id)
        if resume_version_id is not None and not self._resume_versions.exists(resume_version_id):
            raise ResumeVersionNotFoundError("resume version was not found")
        application = self._applications.create(
            saved_job_id,
            resume_version_id=resume_version_id,
            status=status,
            source=source or saved_job.source,
            notes=notes,
            follow_up_date=follow_up_date,
        )
        if notes:
            self.add_application_note(application.id, notes)
        return application

    def list_saved_jobs(
        self,
        *,
        company: str | None = None,
        source: str | None = None,
        active_only: bool = False,
        limit: int | None = None,
    ) -> list[SavedJob]:
        """Return saved jobs using dashboard-friendly filters."""

        if limit is not None and limit < 1:
            raise ApplicationTrackingError("limit must be at least 1")
        return self._saved_jobs.list_all(
            company=company,
            source=source,
            active_only=active_only,
            limit=limit,
        )

    def get_saved_job(self, saved_job_id: str) -> SavedJob:
        """Return one saved-job snapshot."""

        return self._saved_jobs.get(saved_job_id)

    def archive_saved_job(self, saved_job_id: str) -> SavedJob:
        """Archive a saved job without deleting application history."""

        return self._saved_jobs.archive(saved_job_id)

    def get_application(self, application_id: str) -> JobApplication:
        """Return one application record."""

        return self._applications.get(application_id)

    def update_application_status(
        self,
        application_id: str,
        new_status: ApplicationStatus,
        note: str | None = None,
        *,
        changed_at: datetime | None = None,
    ) -> JobApplication:
        """Record a permissive status transition and its event timestamps."""

        updated = self._applications.update_status(
            application_id,
            new_status,
            note=note,
            changed_at=changed_at,
        )
        if note:
            self.add_application_note(
                application_id,
                note,
                self._note_type_for_status(new_status),
            )
        return updated

    def set_follow_up_date(
        self,
        application_id: str,
        follow_up_date: date | None,
    ) -> JobApplication:
        """Set or clear a follow-up date without scheduling notifications."""

        return self._applications.set_follow_up_date(application_id, follow_up_date)

    def set_interview_date(
        self,
        application_id: str,
        interview_date: datetime | None,
    ) -> JobApplication:
        """Set or clear an interview date without calendar integration."""

        return self._applications.set_interview_date(application_id, interview_date)

    def link_resume_version(
        self,
        application_id: str,
        resume_version_id: str | None,
    ) -> JobApplication:
        """Link an existing resume version or clear the current link."""

        self._applications.get(application_id)
        if resume_version_id is not None and not self._resume_versions.exists(resume_version_id):
            raise ResumeVersionNotFoundError("resume version was not found")
        return self._applications.link_resume_version(application_id, resume_version_id)

    def add_application_note(
        self,
        application_id: str,
        note: str,
        note_type: ApplicationNoteType = ApplicationNoteType.GENERAL,
    ) -> ApplicationNote:
        """Append a non-empty note to an application."""

        cleaned = note.strip()
        if not cleaned:
            raise InvalidApplicationNoteError("application note must not be empty")
        return self._applications.add_note(application_id, cleaned, note_type)

    def list_application_notes(self, application_id: str) -> list[ApplicationNote]:
        """Return append-only application notes newest first."""

        return self._applications.list_notes(application_id)

    def list_status_history(self, application_id: str) -> list[ApplicationStatusHistory]:
        """Return the complete chronological status history."""

        return self._applications.list_status_history(application_id)

    def list_applications(
        self,
        filters: ApplicationFilters | None = None,
        *,
        limit: int | None = None,
    ) -> list[JobApplicationSummary]:
        """Return lightweight application summaries matching optional filters."""

        if limit is not None and limit < 1:
            raise ApplicationTrackingError("limit must be at least 1")
        applications = self._applications.list_summaries(filters)
        return applications[:limit] if limit is not None else applications

    def list_follow_ups_due(self, *, as_of_date: date | None = None) -> list[JobApplicationSummary]:
        """Return applications with due follow-up dates and non-terminal statuses."""

        filters = (
            ApplicationFilters(needs_follow_up=True, as_of_date=as_of_date)
            if as_of_date
            else ApplicationFilters(needs_follow_up=True)
        )
        return self.list_applications(filters)

    def get_application_summary(self, application_id: str) -> JobApplicationSummary:
        """Return one lightweight application summary."""

        return self._applications.get_summary(application_id)

    def get_application_history(
        self,
        application_id: str,
    ) -> list[ApplicationStatusHistory]:
        """Return chronological status history using the service-facing name."""

        return self.list_status_history(application_id)

    def _note_type_for_status(self, status: ApplicationStatus) -> ApplicationNoteType:
        mapping = {
            ApplicationStatus.FOLLOW_UP_NEEDED: ApplicationNoteType.FOLLOW_UP,
            ApplicationStatus.INTERVIEWING: ApplicationNoteType.INTERVIEW,
            ApplicationStatus.TECHNICAL_INTERVIEW: ApplicationNoteType.INTERVIEW,
            ApplicationStatus.FINAL_INTERVIEW: ApplicationNoteType.INTERVIEW,
            ApplicationStatus.REJECTED: ApplicationNoteType.REJECTION,
            ApplicationStatus.OFFER: ApplicationNoteType.OFFER,
        }
        return mapping.get(status, ApplicationNoteType.SYSTEM)
