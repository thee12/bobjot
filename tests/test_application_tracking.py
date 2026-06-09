"""Isolated database tests for saved jobs and application pipeline tracking."""

from datetime import UTC, date, datetime, timedelta

import pytest

from ai_internship_assistant.domain.models import (
    ApplicationFilters,
    ApplicationNoteType,
    ApplicationStatus,
    JobApplication,
    JobPosting,
    JobSourceType,
)
from ai_internship_assistant.services import (
    ApplicationTrackingService,
    FullResumeOptimizer,
    InvalidApplicationNoteError,
    ResumeVersioningService,
)
from ai_internship_assistant.storage import (
    ApplicationNotFoundError,
    ApplicationRepository,
    Database,
    JobRepository,
    MasterResumeRepository,
    ResumeVersionNotFoundError,
    ResumeVersionRepository,
    SavedJobNotFoundError,
    SavedJobRepository,
)
from tests.test_full_resume_optimizer import MockBulletRewriter, _request, _safe_packet_rewrite


@pytest.fixture
def tracker() -> tuple[ApplicationTrackingService, ResumeVersioningService]:
    """Create a fresh isolated in-memory application database."""

    database = Database("sqlite://")
    database.initialize()
    versions = ResumeVersionRepository(database)
    tracking = ApplicationTrackingService(
        SavedJobRepository(database),
        ApplicationRepository(database),
        versions,
    )
    versioning = ResumeVersioningService(
        MasterResumeRepository(database),
        versions,
        JobRepository(database),
    )
    return tracking, versioning


def _job(
    *,
    job_id: str = "soc-job",
    title: str = "SOC Analyst Intern",
    company: str = "Example Security",
    location: str = "Raleigh, NC",
    apply_url: str | None = "https://jobs.example.com/soc?utm_source=test",
    source_url: str | None = "https://jobs.example.com/postings/soc",
) -> JobPosting:
    return JobPosting(
        id=job_id,
        source=JobSourceType.MANUAL,
        source_name="Manual",
        source_url=source_url,
        apply_url=apply_url,
        title=title,
        company=company,
        location=location,
        description="Entry-level security internship.",
    )


def _saved_application(
    tracker: ApplicationTrackingService,
    *,
    job: JobPosting | None = None,
    status: ApplicationStatus = ApplicationStatus.PLANNED,
    resume_version_id: str | None = None,
) -> JobApplication:
    saved = tracker.save_job(job or _job())
    return tracker.create_application(saved.id, resume_version_id, status)


def _save_resume_version(versioning: ResumeVersioningService) -> str:
    request = _request()
    master = versioning.save_master_resume(request.resume)
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(request)
    return versioning.save_optimized_resume(master.id, result).id


def test_save_job_preserves_snapshot_scores_and_analysis(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    request = _request()

    saved = service.save_job(
        _job(),
        request.job_analysis,
        request.ats_match_report,
        fit_score=88.5,
    )

    assert saved.job_posting_id == "soc-job"
    assert saved.job_analysis == request.job_analysis
    assert saved.ats_match_report == request.ats_match_report
    assert saved.ats_score == request.ats_match_report.overall_score
    assert saved.fit_score == 88.5


def test_save_duplicate_job_updates_last_seen_without_creating_duplicate(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    first = service.save_job(_job())
    second = service.save_job(_job())

    assert second.id == first.id
    assert second.saved_at == first.saved_at
    assert second.last_seen_at >= first.last_seen_at


def test_duplicate_normalized_apply_url_is_detected(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    first = service.save_job(_job())
    duplicate = _job(
        job_id="provider-copy",
        apply_url="https://jobs.example.com/soc?utm_campaign=duplicate",
        source_url="https://other.example.com/soc",
    )

    second = service.save_job(duplicate)

    assert second.id == first.id
    assert second.job_posting_id == first.job_posting_id
    assert second.job_posting.id == first.job_posting.id


def test_duplicate_company_title_location_fingerprint_is_detected(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    first = service.save_job(_job(apply_url=None, source_url=None))
    second = service.save_job(_job(job_id="copy", apply_url=None, source_url=None))

    assert second.id == first.id


def test_explicit_duplicate_is_allowed(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    first = service.save_job(_job())
    second = service.save_job(_job(), allow_duplicate=True)

    assert second.id != first.id


def test_list_filter_and_archive_saved_jobs(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    target = service.save_job(_job())
    service.save_job(
        _job(
            job_id="other",
            title="Software Intern",
            company="Other Company",
            apply_url="https://other.example.com/apply",
            source_url="https://other.example.com/job",
        )
    )

    assert [item.id for item in service.list_saved_jobs(company="Example", limit=1)] == [target.id]
    archived = service.archive_saved_job(target.id)

    assert archived.is_active is False
    assert service.list_saved_jobs(active_only=True) == [
        item for item in service.list_saved_jobs() if item.id != target.id
    ]


def test_create_application_defaults_to_planned(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker

    application = _saved_application(service)

    assert application.status is ApplicationStatus.PLANNED
    assert application.applied_at is None


def test_create_application_links_existing_resume_version(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, versioning = tracker
    version_id = _save_resume_version(versioning)

    application = _saved_application(service, resume_version_id=version_id)

    assert application.resume_version_id == version_id


def test_link_resume_version_after_application_creation(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, versioning = tracker
    version_id = _save_resume_version(versioning)
    application = _saved_application(service)

    linked = service.link_resume_version(application.id, version_id)

    assert linked.resume_version_id == version_id


def test_create_application_note_is_append_only_note(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    saved = service.save_job(_job())

    application = service.create_application(saved.id, notes="Planning to apply.")

    assert service.list_application_notes(application.id)[0].note == "Planning to apply."


def test_missing_saved_job_and_resume_version_raise_meaningful_errors(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    saved = service.save_job(_job())

    with pytest.raises(SavedJobNotFoundError):
        service.create_application("missing")
    with pytest.raises(ResumeVersionNotFoundError):
        service.create_application(saved.id, "missing")


def test_status_update_records_history_and_note(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)

    updated = service.update_application_status(
        application.id,
        ApplicationStatus.READY_TO_APPLY,
        "Resume reviewed.",
    )
    history = service.list_status_history(application.id)
    notes = service.list_application_notes(application.id)

    assert updated.status is ApplicationStatus.READY_TO_APPLY
    assert [item.new_status for item in history] == [
        ApplicationStatus.PLANNED,
        ApplicationStatus.READY_TO_APPLY,
    ]
    assert notes[0].note == "Resume reviewed."


@pytest.mark.parametrize(
    ("status", "field_name"),
    [
        (ApplicationStatus.APPLIED, "applied_at"),
        (ApplicationStatus.REJECTED, "rejected_at"),
        (ApplicationStatus.OFFER, "offer_received_at"),
        (ApplicationStatus.WITHDRAWN, "withdrawn_at"),
        (ApplicationStatus.INTERVIEWING, "response_received_at"),
        (ApplicationStatus.TECHNICAL_INTERVIEW, "response_received_at"),
    ],
)
def test_status_updates_set_expected_timestamp(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
    status: ApplicationStatus,
    field_name: str,
) -> None:
    service, _ = tracker
    application = _saved_application(service)

    updated = service.update_application_status(application.id, status)

    assert getattr(updated, field_name) is not None


def test_existing_status_timestamps_are_not_overwritten(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)
    first = service.update_application_status(application.id, ApplicationStatus.APPLIED)

    service.update_application_status(application.id, ApplicationStatus.INTERVIEWING)
    second = service.update_application_status(application.id, ApplicationStatus.APPLIED)

    assert second.applied_at == first.applied_at


def test_add_application_notes_is_append_only(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)

    service.add_application_note(application.id, "Applied through company site.")
    service.add_application_note(
        application.id,
        "Follow up Friday.",
        ApplicationNoteType.FOLLOW_UP,
    )
    notes = service.list_application_notes(application.id)

    assert {note.note for note in notes} == {
        "Applied through company site.",
        "Follow up Friday.",
    }
    assert len({note.id for note in notes}) == 2


def test_empty_note_and_missing_application_raise_meaningful_errors(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)

    with pytest.raises(InvalidApplicationNoteError):
        service.add_application_note(application.id, "   ")
    with pytest.raises(ApplicationNotFoundError):
        service.add_application_note("missing", "note")


def test_list_applications_filters_status_company_role_and_source(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    target = _saved_application(service, status=ApplicationStatus.APPLIED)
    _saved_application(
        service,
        job=_job(
            job_id="software-job",
            title="Software Engineering Intern",
            company="Other Company",
            apply_url="https://other.example.com/apply",
            source_url="https://other.example.com/job",
        ),
    )

    assert [item.id for item in service.list_applications(
        ApplicationFilters(status=ApplicationStatus.APPLIED)
    )] == [target.id]
    assert [item.id for item in service.list_applications(
        ApplicationFilters(company="Example")
    )] == [target.id]
    assert [item.id for item in service.list_applications(
        ApplicationFilters(role_keyword="SOC")
    )] == [target.id]
    assert {
        item.id for item in service.list_applications(ApplicationFilters(source="manual"))
    } == {item.id for item in service.list_applications()}


def test_filter_by_applied_date_range(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)
    applied_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    service.update_application_status(
        application.id,
        ApplicationStatus.APPLIED,
        changed_at=applied_at,
    )

    included = service.list_applications(
        ApplicationFilters(
            applied_after=applied_at - timedelta(days=1),
            applied_before=applied_at + timedelta(days=1),
        )
    )
    excluded = service.list_applications(
        ApplicationFilters(applied_after=applied_at + timedelta(days=1))
    )

    assert [item.id for item in included] == [application.id]
    assert excluded == []


def test_follow_up_filter_returns_due_non_terminal_applications(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    due = _saved_application(service)
    terminal = _saved_application(
        service,
        job=_job(
            job_id="closed-job",
            title="Security Intern",
            apply_url="https://closed.example.com/apply",
            source_url="https://closed.example.com/job",
        ),
        status=ApplicationStatus.REJECTED,
    )
    service.set_follow_up_date(due.id, date(2026, 6, 8))
    service.set_follow_up_date(terminal.id, date(2026, 6, 8))

    results = service.list_applications(
        ApplicationFilters(needs_follow_up=True, as_of_date=date(2026, 6, 9))
    )

    assert [item.id for item in results] == [due.id]


def test_negative_follow_up_filter_includes_records_without_due_dates(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    application = _saved_application(service)

    results = service.list_applications(
        ApplicationFilters(needs_follow_up=False, as_of_date=date(2026, 6, 9))
    )

    assert [item.id for item in results] == [application.id]


def test_interview_filter_uses_status_or_scheduled_date(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    interviewing = _saved_application(service, status=ApplicationStatus.INTERVIEWING)
    scheduled = _saved_application(
        service,
        job=_job(
            job_id="scheduled-job",
            title="Network Intern",
            apply_url="https://network.example.com/apply",
            source_url="https://network.example.com/job",
        ),
    )
    service.set_interview_date(scheduled.id, datetime(2026, 6, 15, 14, 0, tzinfo=UTC))

    results = service.list_applications(ApplicationFilters(has_interview=True))

    assert {item.id for item in results} == {interviewing.id, scheduled.id}


def test_filter_by_resume_version(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, versioning = tracker
    version_id = _save_resume_version(versioning)
    linked = _saved_application(service, resume_version_id=version_id)
    _saved_application(
        service,
        job=_job(
            job_id="unlinked-job",
            title="Cybersecurity Intern",
            apply_url="https://unlinked.example.com/apply",
            source_url="https://unlinked.example.com/job",
        ),
    )

    results = service.list_applications(ApplicationFilters(resume_version_id=version_id))

    assert [item.id for item in results] == [linked.id]


def test_application_summary_contains_scores_and_latest_note(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker
    request = _request()
    saved = service.save_job(
        _job(),
        request.job_analysis,
        request.ats_match_report,
        fit_score=91.0,
    )
    application = service.create_application(saved.id)
    service.add_application_note(application.id, "First note.")
    service.add_application_note(application.id, "Latest note.")

    summary = service.get_application_summary(application.id)

    assert summary.title == "SOC Analyst Intern"
    assert summary.ats_score == request.ats_match_report.overall_score
    assert summary.fit_score == 91.0
    assert summary.latest_note == "Latest note."


def test_each_tracker_test_uses_an_isolated_database(
    tracker: tuple[ApplicationTrackingService, ResumeVersioningService],
) -> None:
    service, _ = tracker

    assert service.list_applications() == []
