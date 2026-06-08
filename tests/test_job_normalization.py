"""Tests for deterministic job normalization and conservative deduplication."""

from ai_internship_assistant.domain.models import (
    JobPosting,
    JobSearchQuery,
    JobSearchQuerySet,
    JobSourceType,
    QueryPriority,
    SearchEmploymentType,
)
from ai_internship_assistant.services.job_normalization import (
    JobDeduplicationService,
    JobNormalizationService,
)
from ai_internship_assistant.services.job_sources import JobSearchService, JobSource


def _job(
    *,
    identifier: str,
    source: JobSourceType = JobSourceType.MOCK,
    title: str = "Software Engineering Intern",
    company: str = "Cisco",
    location: str | None = "Raleigh, NC",
    apply_url: str | None = None,
    source_url: str | None = None,
    description: str | None = "Build software.",
    technologies: list[str] | None = None,
) -> JobPosting:
    """Build a standardized posting for normalization tests."""

    return JobPosting(
        id=identifier,
        source=source,
        source_name=source.value,
        title=title,
        company=company,
        location=location,
        apply_url=apply_url,
        source_url=source_url,
        description=description,
        technologies=technologies or [],
    )


def test_identical_normalized_apply_urls_deduplicate() -> None:
    """Tracking parameters should not prevent identical apply URLs from merging."""

    jobs = [
        _job(
            identifier="1",
            apply_url="https://jobs.example.com/apply?id=123&utm_source=abc",
        ),
        _job(identifier="2", apply_url="https://jobs.example.com/apply?id=123"),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 1
    assert result.duplicate_count == 1
    assert result.duplicate_groups[0].confidence_score == 1.0
    assert result.duplicate_groups[0].reason == "identical normalized apply URL"


def test_identical_normalized_source_urls_deduplicate() -> None:
    """Identical source URLs should merge when apply URLs are unavailable."""

    jobs = [
        _job(identifier="1", source_url="https://jobs.example.com/role/123?gh_src=abc"),
        _job(identifier="2", source_url="https://jobs.example.com/role/123"),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 1
    assert result.duplicate_groups[0].confidence_score == 0.95


def test_same_company_title_and_location_deduplicate() -> None:
    """Company aliases, title variants, and equivalent locations should merge."""

    jobs = [
        _job(
            identifier="1",
            title="Software Engineer Intern - Summer 2026",
            company="Cisco Systems, Inc.",
            location="Raleigh, North Carolina, United States",
        ),
        _job(
            identifier="2",
            title="Software Engineering Internship",
            company="Cisco",
            location="Raleigh, NC",
        ),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 1
    assert result.duplicate_groups[0].confidence_score == 0.85


def test_similar_but_different_jobs_do_not_deduplicate() -> None:
    """Related roles should remain separate when identity similarity is insufficient."""

    jobs = [
        _job(identifier="1", title="Software Engineering Intern"),
        _job(identifier="2", title="Product Management Intern"),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 2
    assert result.duplicate_groups == []


def test_different_locations_do_not_deduplicate_aggressively() -> None:
    """Same role at different locations should remain separate."""

    jobs = [
        _job(identifier="1", location="Raleigh, NC"),
        _job(identifier="2", location="Austin, TX"),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 2


def test_remote_location_normalization() -> None:
    """Remote location variants should normalize consistently."""

    normalizer = JobNormalizationService()

    locations = {
        normalizer.normalize(_job(identifier="1", location="Remote")).normalized_location,
        normalizer.normalize(
            _job(identifier="2", location="Remote - United States")
        ).normalized_location,
        normalizer.normalize(
            _job(identifier="3", location="United States Remote")
        ).normalized_location,
    }

    assert locations == {"remote"}


def test_company_alias_normalization() -> None:
    """Small expandable aliases should normalize common company variants."""

    normalizer = JobNormalizationService()

    companies = {
        normalizer.normalize(_job(identifier="1", company="Cisco")).normalized_company,
        normalizer.normalize(_job(identifier="2", company="Cisco Systems")).normalized_company,
        normalizer.normalize(
            _job(identifier="3", company="Cisco Systems, Inc.")
        ).normalized_company,
    }

    assert companies == {"cisco"}


def test_title_normalization() -> None:
    """Common internship title variants should normalize consistently."""

    normalizer = JobNormalizationService()

    titles = {
        normalizer.normalize(
            _job(identifier="1", title="Software Engineer Intern")
        ).normalized_title,
        normalizer.normalize(
            _job(identifier="2", title="Software Engineering Internship")
        ).normalized_title,
        normalizer.normalize(
            _job(identifier="3", title="Software Engineering Intern - Summer 2026")
        ).normalized_title,
    }

    assert titles == {"software engineering intern"}


def test_url_tracking_parameters_are_removed_without_breaking_query() -> None:
    """Known tracking parameters should be removed while identity parameters remain."""

    normalized = JobNormalizationService().normalize(
        _job(
            identifier="1",
            apply_url=(
                "https://jobs.example.com/apply?id=123&utm_source=test"
                "&utm_campaign=summer&lever-source=board"
            ),
        )
    )

    assert normalized.normalized_apply_url == "https://jobs.example.com/apply?id=123"


def test_description_whitespace_and_html_cleanup() -> None:
    """Description normalization should clean formatting without summarizing."""

    normalized = JobNormalizationService().normalize(
        _job(identifier="1", description="<p>Build software.</p>\n\n  Test APIs.  ")
    )

    assert normalized.normalized_description_text == "Build software. Test APIs."


def test_canonical_job_prefers_more_complete_description() -> None:
    """Canonical selection should prefer the most complete posting."""

    short = _job(
        identifier="short",
        apply_url="https://jobs.example.com/apply?id=123",
        description="Build software.",
    )
    complete = _job(
        identifier="complete",
        source=JobSourceType.GREENHOUSE,
        apply_url="https://jobs.example.com/apply?id=123&utm_source=test",
        description="Build software, write tests, review changes, and document the API.",
        technologies=["Python", "Git"],
    )

    group = JobDeduplicationService().deduplicate([short, complete]).duplicate_groups[0]

    assert group.canonical_job is complete


def test_duplicate_group_preserves_original_jobs() -> None:
    """Duplicate groups should preserve original posting references and sources."""

    greenhouse = _job(
        identifier="greenhouse",
        source=JobSourceType.GREENHOUSE,
        apply_url="https://jobs.example.com/apply?id=123",
    )
    lever = _job(
        identifier="lever",
        source=JobSourceType.LEVER,
        apply_url="https://jobs.example.com/apply?id=123&utm_medium=referral",
    )

    group = JobDeduplicationService().deduplicate([greenhouse, lever]).duplicate_groups[0]

    preserved = [group.canonical_job, *group.duplicate_jobs]
    assert {job.source for job in preserved} == {JobSourceType.GREENHOUSE, JobSourceType.LEVER}
    assert group.duplicate_count == 1


def test_empty_job_list() -> None:
    """Empty inputs should return an empty clean result."""

    result = JobDeduplicationService().deduplicate([])

    assert result.original_count == 0
    assert result.unique_count == 0
    assert result.duplicate_count == 0
    assert result.unique_jobs == []


def test_partially_populated_jobs_with_missing_company_or_title() -> None:
    """Normalization should tolerate partially parsed jobs without merging them."""

    missing_company = JobPosting.model_construct(
        id="1",
        source=JobSourceType.MOCK,
        source_name="mock",
        title="Software Intern",
        company=None,
    )
    missing_title = JobPosting.model_construct(
        id="2",
        source=JobSourceType.MOCK,
        source_name="mock",
        title=None,
        company="Example Company",
    )

    normalized = JobNormalizationService().normalize_many([missing_company, missing_title])
    result = JobDeduplicationService().deduplicate([missing_company, missing_title])

    assert normalized[0].normalized_company == ""
    assert normalized[1].normalized_title == ""
    assert result.unique_count == 2


class StaticJobSource(JobSource):
    """Test source returning predefined postings."""

    def __init__(self, name: str, source_type: JobSourceType, jobs: list[JobPosting]) -> None:
        self._name = name
        self._source_type = source_type
        self._jobs = jobs

    @property
    def source_name(self) -> str:
        return self._name

    @property
    def source_type(self) -> JobSourceType:
        return self._source_type

    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        return self._jobs


def test_integration_with_job_search_service() -> None:
    """Search service should optionally expose normalized and deduplicated results."""

    first = _job(identifier="1", apply_url="https://jobs.example.com/apply?id=123")
    second = _job(
        identifier="2",
        apply_url="https://jobs.example.com/apply?id=123&utm_source=test",
    )
    query = JobSearchQuery(
        query_text="Software Engineering Intern",
        role="Software Engineering Intern",
        employment_type=SearchEmploymentType.INTERNSHIP,
        priority=QueryPriority.HIGH,
        reason="Test.",
        max_results=25,
    )
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService(
        [StaticJobSource("Static", JobSourceType.MOCK, [first, second])],
        normalize=True,
        deduplicate=True,
    ).search_all(query_set)

    assert len(result.normalized_jobs) == 2
    assert result.total_found == 1
    assert result.deduplication_result is not None
    assert result.deduplication_result.original_count == 2


def test_greenhouse_and_lever_duplicate_simulated_together() -> None:
    """Equivalent direct ATS postings should merge without source-specific logic."""

    greenhouse = _job(
        identifier="gh-1",
        source=JobSourceType.GREENHOUSE,
        title="Software Engineer Intern - Summer 2026",
        company="Cisco Systems, Inc.",
        location="Raleigh, North Carolina, United States",
        source_url="https://boards.greenhouse.io/cisco/jobs/123?gh_src=test",
    )
    lever = _job(
        identifier="lever-1",
        source=JobSourceType.LEVER,
        title="Software Engineering Internship",
        company="Cisco",
        location="Raleigh, NC",
        source_url="https://jobs.lever.co/cisco/456",
    )

    result = JobDeduplicationService().deduplicate([greenhouse, lever])

    assert result.unique_count == 1
    assert result.duplicate_groups[0].confidence_score == 0.85


def test_unknown_location_possible_duplicate_is_retained_with_warning() -> None:
    """Below-threshold possible duplicates should remain separate with a warning."""

    jobs = [
        _job(identifier="1", location=None),
        _job(identifier="2", location="Raleigh, NC"),
    ]

    result = JobDeduplicationService().deduplicate(jobs)

    assert result.unique_count == 2
    assert result.warnings
