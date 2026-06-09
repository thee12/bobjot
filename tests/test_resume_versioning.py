"""Repository and service tests for immutable resume version persistence."""

import pytest

from ai_internship_assistant.domain.models import (
    JobPosting,
    JobSourceType,
    OptimizedResumeResult,
    ResumeSourceFileMetadata,
    ResumeVersionSummary,
    StoredResume,
    StoredResumeVersion,
)
from ai_internship_assistant.services import (
    FullResumeOptimizer,
    InvalidResumeVersionRelationshipError,
    ResumeVersionComparisonService,
    ResumeVersioningService,
)
from ai_internship_assistant.storage import (
    CorruptedArtifactError,
    Database,
    DuplicateMasterResumeError,
    JobNotFoundError,
    JobRepository,
    MasterResumeNotFoundError,
    MasterResumeRepository,
    ResumeVersionNotFoundError,
    ResumeVersionRepository,
)
from ai_internship_assistant.storage.database import ResumeVersionRow
from tests.test_full_resume_optimizer import MockBulletRewriter, _request, _safe_packet_rewrite


@pytest.fixture
def persistence() -> tuple[
    Database,
    MasterResumeRepository,
    ResumeVersionRepository,
    JobRepository,
    ResumeVersioningService,
]:
    """Create a fresh isolated in-memory database for every test."""

    database = Database("sqlite://")
    database.initialize()
    masters = MasterResumeRepository(database)
    versions = ResumeVersionRepository(database)
    jobs = JobRepository(database)
    service = ResumeVersioningService(masters, versions, jobs)
    return database, masters, versions, jobs, service


def _optimized_result() -> OptimizedResumeResult:
    return FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())


def _save_master(service: ResumeVersioningService) -> StoredResume:
    request = _request()
    metadata = ResumeSourceFileMetadata(
        original_filename="resume.pdf",
        file_type="pdf",
        file_size_bytes=1_024,
        content_hash="file-hash",
    )
    return service.save_master_resume(
        request.resume,
        metadata,
        source_text="Alex Candidate Python Linux resume",
    )


def _save_job(jobs: JobRepository) -> None:
    request = _request()
    posting = JobPosting(
        id=request.job_analysis.job_id,
        source=JobSourceType.MANUAL,
        source_name="Manual",
        title=request.job_analysis.job_title,
        company=request.job_analysis.company,
        description="SOC internship.",
    )
    jobs.save(posting, request.job_analysis)


def test_save_retrieve_and_list_master_resume(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    stored = _save_master(service)
    retrieved = service.get_master_resume(stored.id)

    assert retrieved.parsed_resume == _request().resume
    assert retrieved.is_master is True
    assert service.list_master_resumes() == [retrieved]


def test_duplicate_normalized_source_text_is_detected(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    resume = _request().resume
    service.save_master_resume(resume, source_text="same   resume text")

    with pytest.raises(DuplicateMasterResumeError):
        service.save_master_resume(resume, source_text="same resume text")


def test_save_and_retrieve_complete_optimized_version(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, jobs, service = persistence
    master = _save_master(service)
    _save_job(jobs)
    result = _optimized_result()

    stored = service.save_optimized_resume(master.id, result, target_job_id="soc-job")
    retrieved = service.get_resume_version(stored.id)

    assert retrieved.optimized_resume == result.optimized_resume
    assert retrieved.optimization_plan == result.optimization_plan
    assert retrieved.skill_gap_report == result.skill_gap_report
    assert retrieved.ats_match_report == result.ats_match_report
    assert retrieved.safety_report == result.safety_report
    assert retrieved.change_log == result.changes
    assert retrieved.target_job_id == "soc-job"


def test_two_versions_for_same_job_are_immutable_and_names_avoid_duplicates(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, jobs, service = persistence
    master = _save_master(service)
    _save_job(jobs)
    result = _optimized_result()

    first = service.save_optimized_resume(master.id, result, target_job_id="soc-job")
    second = service.save_optimized_resume(master.id, result, target_job_id="soc-job")

    assert first.id != second.id
    assert first.version_name == "SOC Analyst Intern - Example Security"
    assert second.version_name == "SOC Analyst Intern - Example Security v2"
    assert service.get_resume_version(first.id).optimized_resume == first.optimized_resume


def test_master_resume_is_not_overwritten_by_version(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    original = master.parsed_resume.model_dump()

    service.save_optimized_resume(master.id, _optimized_result())

    assert service.get_master_resume(master.id).parsed_resume.model_dump() == original


def test_lists_versions_summaries_and_latest_for_job(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, jobs, service = persistence
    master = _save_master(service)
    _save_job(jobs)
    result = _optimized_result()
    first = service.save_optimized_resume(master.id, result, target_job_id="soc-job")
    second = service.save_optimized_resume(master.id, result, target_job_id="soc-job")

    versions = service.list_versions_for_master_resume(master.id)
    summaries = service.get_version_summaries(master.id)

    assert {version.id for version in versions} == {first.id, second.id}
    assert {version.id for version in service.list_versions_for_job("soc-job")} == {
        first.id,
        second.id,
    }
    assert all(isinstance(summary, ResumeVersionSummary) for summary in summaries)
    assert service.get_latest_version_for_job("soc-job").id == second.id


def test_scores_and_optimizer_metadata_are_preserved(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    result = _optimized_result()

    stored = service.save_optimized_resume(master.id, result)

    assert stored.before_ats_score == result.before_ats_score
    assert stored.estimated_after_score_low == result.estimated_after_ats_score.low
    assert stored.estimated_after_score_high == result.estimated_after_ats_score.high
    assert stored.optimizer_version == result.optimizer_version


def test_missing_master_and_invalid_version_raise_meaningful_errors(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    with pytest.raises(MasterResumeNotFoundError):
        service.save_optimized_resume("missing", _optimized_result())
    with pytest.raises(ResumeVersionNotFoundError):
        service.get_resume_version("missing")


def test_corrupted_json_is_reported_without_exposing_contents(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    database, _, _, _, service = persistence
    master = _save_master(service)
    stored = service.save_optimized_resume(master.id, _optimized_result())
    with database.session() as session:
        row = session.get(ResumeVersionRow, stored.id)
        assert row is not None
        row.optimized_resume_json = "{corrupted"

    with pytest.raises(CorruptedArtifactError, match="stored resume version data is corrupted"):
        service.get_resume_version(stored.id)


def test_round_trip_preserves_nested_models(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    result = _optimized_result()

    stored = service.save_optimized_resume(master.id, result)
    round_trip = StoredResumeVersion.model_validate(stored.model_dump())

    assert round_trip == stored
    assert round_trip.change_log
    assert round_trip.model_schema_version == "1"


def test_only_notes_can_be_updated(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    stored = service.save_optimized_resume(master.id, _optimized_result())
    content_hash = stored.optimized_content_hash

    updated = service.update_version_notes(stored.id, ["Reviewed by candidate."])

    assert updated.notes == ["Reviewed by candidate."]
    assert updated.optimized_content_hash == content_hash
    assert updated.optimized_resume == stored.optimized_resume


def test_comparison_service_returns_lightweight_metadata(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, versions, _, service = persistence
    master = _save_master(service)
    first = service.save_optimized_resume(master.id, _optimized_result())
    second = service.save_optimized_resume(master.id, _optimized_result())

    comparison = ResumeVersionComparisonService(versions).compare_versions(first.id, second.id)

    assert comparison.version_a.id == first.id
    assert comparison.version_b.id == second.id
    assert comparison.warnings


def test_each_test_uses_isolated_database(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    assert service.list_master_resumes() == []


def test_master_file_metadata_is_preserved(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    master = _save_master(service)

    assert master.original_filename == "resume.pdf"
    assert master.source_file_metadata
    assert master.source_file_metadata.content_hash == "file-hash"


def test_saved_job_round_trip(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, jobs, _ = persistence
    _save_job(jobs)

    job = jobs.get("soc-job")

    assert job.title == "SOC Analyst Intern"
    assert job.job_analysis
    assert job.job_analysis.job_id == "soc-job"


def test_invalid_target_job_relationship_is_rejected(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)

    with pytest.raises(InvalidResumeVersionRelationshipError):
        service.save_optimized_resume(master.id, _optimized_result(), target_job_id="missing")


def test_empty_version_lists_are_supported(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)

    assert service.list_versions_for_master_resume(master.id) == []
    assert service.get_version_summaries(master.id) == []


def test_latest_version_for_unknown_job_is_none(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    assert service.get_latest_version_for_job("unknown") is None


def test_identical_optimized_versions_share_content_hash(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    result = _optimized_result()

    first = service.save_optimized_resume(master.id, result)
    second = service.save_optimized_resume(master.id, result)

    assert first.optimized_content_hash == second.optimized_content_hash


def test_duplicate_structured_master_is_detected_without_source_text(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    resume = _request().resume
    service.save_master_resume(resume)

    with pytest.raises(DuplicateMasterResumeError):
        service.save_master_resume(resume)


def test_updating_missing_version_notes_raises(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence

    with pytest.raises(ResumeVersionNotFoundError):
        service.update_version_notes("missing", ["note"])


def test_missing_job_raises_meaningful_error(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, jobs, _ = persistence

    with pytest.raises(JobNotFoundError):
        jobs.get("missing")


def test_version_name_falls_back_when_target_metadata_is_empty(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, _, _, service = persistence
    master = _save_master(service)
    result = _optimized_result()
    result = result.model_copy(
        update={
            "optimized_resume": result.optimized_resume.model_copy(
                update={"target_job_title": "", "target_company": ""}
            )
        }
    )

    stored = service.save_optimized_resume(master.id, result)

    assert stored.version_name == "Optimized Resume - Version 1"


def test_schema_version_difference_returns_compatibility_warning(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    database, _, _, _, service = persistence
    master = _save_master(service)
    stored = service.save_optimized_resume(master.id, _optimized_result())
    with database.session() as session:
        row = session.get(ResumeVersionRow, stored.id)
        assert row is not None
        row.model_schema_version = "0"

    retrieved = service.get_resume_version(stored.id)

    assert retrieved.compatibility_warnings


def test_comparison_with_invalid_version_raises(
    persistence: tuple[
        Database,
        MasterResumeRepository,
        ResumeVersionRepository,
        JobRepository,
        ResumeVersioningService,
    ],
) -> None:
    _, _, versions, _, _ = persistence

    with pytest.raises(ResumeVersionNotFoundError):
        ResumeVersionComparisonService(versions).compare_versions("missing-a", "missing-b")
