"""Tests for standardized job postings and job-source abstractions."""

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobPosting,
    JobSearchErrorType,
    JobSearchQuery,
    JobSearchQuerySet,
    JobSourceType,
    QueryPriority,
    SearchEmploymentType,
    WorkArrangement,
)
from ai_internship_assistant.services.job_sources import (
    JobSearchService,
    JobSource,
    JobSourceSearchError,
    MockJobSource,
)


def _query(
    *,
    role: str = "Cybersecurity Intern",
    location: str | None = "Raleigh, NC",
    remote: bool = False,
) -> JobSearchQuery:
    """Build one structured query for source tests."""

    return JobSearchQuery(
        query_text=f"{role} {location or ''}".strip(),
        role=role,
        location=location,
        employment_type=SearchEmploymentType.INTERNSHIP,
        remote=remote,
        priority=QueryPriority.HIGH,
        reason="Test query.",
        max_results=25,
    )


def test_job_posting_model_construction_and_normalization() -> None:
    """Provider data should become a normalized internal JobPosting."""

    posting = JobPosting(
        id="job-1",
        source=JobSourceType.GREENHOUSE,
        source_name="  Greenhouse  ",
        source_url="https://boards.greenhouse.io/example/jobs/1",
        apply_url="https://boards.greenhouse.io/example/jobs/1/apply",
        title="  Cybersecurity   Intern ",
        company=" Example   Security Company ",
        location=" Raleigh,   NC ",
        employment_type=EmploymentType.INTERNSHIP,
        work_arrangement=WorkArrangement.HYBRID,
        description="Original provider description.",
        raw_data={"provider_id": 1},
    )

    assert posting.title == "Cybersecurity Intern"
    assert posting.company == "Example Security Company"
    assert posting.location == "Raleigh, NC"
    assert posting.source_name == "Greenhouse"
    assert posting.normalized_title == "cybersecurity intern"
    assert posting.normalized_company == "example security company"
    assert str(posting.canonical_url) == "https://boards.greenhouse.io/example/jobs/1/apply"
    assert posting.raw_data == {"provider_id": 1}


def test_mock_job_source_returns_realistic_standardized_results() -> None:
    """The development mock should return standardized jobs without network calls."""

    jobs = MockJobSource().search(_query())

    assert jobs
    assert jobs[0].title == "Cybersecurity Intern"
    assert jobs[0].company == "Example Security Company"
    assert jobs[0].location == "Raleigh, NC"
    assert jobs[0].employment_type == EmploymentType.INTERNSHIP
    assert jobs[0].source == JobSourceType.MOCK
    assert jobs[0].raw_data["development_mock"] is True


def test_job_search_service_with_one_source() -> None:
    """The service should aggregate results from one source."""

    query = _query()
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService([MockJobSource()]).search_all(query_set)

    assert result.total_found == len(result.jobs)
    assert result.total_found > 0
    assert len(result.source_results) == 1
    assert result.errors == []


def test_job_search_service_with_multiple_mock_sources() -> None:
    """The service should preserve results from multiple configured sources."""

    query = _query(role="Software Engineering Intern")
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])
    sources = [MockJobSource(name="Mock Alpha"), MockJobSource(name="Mock Beta")]

    result = JobSearchService(sources).search_all(query_set)

    assert result.total_found == 2
    assert {job.source_name for job in result.jobs} == {"Mock Alpha", "Mock Beta"}
    assert len(result.source_results) == 2


class FailingJobSource(JobSource):
    """Test source that emits one expected recoverable failure."""

    @property
    def source_name(self) -> str:
        return "Failing Source"

    @property
    def source_type(self) -> JobSourceType:
        return JobSourceType.COMPANY_PAGE

    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        raise JobSourceSearchError(
            f"Temporary failure for {query.query_text}",
            error_type=JobSearchErrorType.NETWORK,
            recoverable=True,
        )


def test_source_failure_does_not_discard_successful_results() -> None:
    """One expected source failure should not crash or erase other results."""

    query = _query()
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService([FailingJobSource(), MockJobSource()]).search_all(query_set)

    assert result.jobs
    assert len(result.errors) == 1
    assert result.errors[0].source_name == "Failing Source"
    assert result.errors[0].error_type == JobSearchErrorType.NETWORK
    assert result.errors[0].recoverable


def test_employment_type_normalization() -> None:
    """Common provider employment labels should normalize predictably."""

    assert JobPosting.normalize_employment_type("Intern") == EmploymentType.INTERNSHIP
    assert JobPosting.normalize_employment_type("Full Time") == EmploymentType.FULL_TIME
    assert JobPosting.normalize_employment_type("part-time") == EmploymentType.PART_TIME
    assert JobPosting.normalize_employment_type("Temp") == EmploymentType.TEMPORARY
    assert JobPosting.normalize_employment_type("other") == EmploymentType.UNKNOWN


def test_work_arrangement_normalization() -> None:
    """Common provider arrangement labels should normalize predictably."""

    assert JobPosting.normalize_work_arrangement("Remote - US") == WorkArrangement.REMOTE
    assert JobPosting.normalize_work_arrangement("Hybrid") == WorkArrangement.HYBRID
    assert JobPosting.normalize_work_arrangement("On Site") == WorkArrangement.ONSITE
    assert JobPosting.normalize_work_arrangement("Flexible") == WorkArrangement.UNKNOWN


def test_job_fingerprint_is_stable_and_changes_with_identity() -> None:
    """Fingerprint helpers should support future deduplication."""

    common = {
        "id": "job-1",
        "source": JobSourceType.MOCK,
        "source_name": "Mock",
        "source_url": "https://example.test/jobs/1",
        "title": "Cybersecurity Intern",
        "company": "Example Security Company",
        "location": "Raleigh, NC",
    }
    first = JobPosting(**common)
    same_identity = JobPosting(**{**common, "id": "different-provider-id"})
    different_location = JobPosting(**{**common, "location": "Durham, NC"})

    assert first.fingerprint == same_identity.fingerprint
    assert first.fingerprint != different_location.fingerprint


def test_empty_query_returns_empty_results() -> None:
    """A malformed blank query should degrade to no mock results."""

    query = JobSearchQuery.model_construct(
        query_text="",
        role="",
        location=None,
        employment_type=SearchEmploymentType.INTERNSHIP,
        remote=False,
        hybrid=False,
        priority=QueryPriority.HIGH,
        source_hint=None,
        reason="Malformed test query.",
        max_results=25,
    )
    query_set = JobSearchQuerySet(queries=[query])

    result = JobSearchService([MockJobSource()]).search_all(query_set)

    assert result.jobs == []
    assert result.total_found == 0
    assert result.errors == []


def test_empty_result_is_represented_without_error() -> None:
    """No source matches should produce a successful empty result."""

    query = _query(role="Quantum Hardware Intern")
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService([MockJobSource()]).search_all(query_set)

    assert result.jobs == []
    assert result.errors == []
    assert result.source_results[0].total_found == 0


def test_empty_query_set_skips_all_sources() -> None:
    """An empty query set should return an empty aggregate result."""

    result = JobSearchService([MockJobSource()]).search_all(JobSearchQuerySet())

    assert result.jobs == []
    assert result.source_results == []
    assert result.total_found == 0
