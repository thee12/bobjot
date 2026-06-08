"""Tests for the public Lever Postings API adapter."""

import json
from pathlib import Path

import httpx

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobSearchErrorType,
    JobSearchQuery,
    JobSearchQuerySet,
    JobSourceType,
    QueryPriority,
    SearchEmploymentType,
    WorkArrangement,
)
from ai_internship_assistant.services.job_sources import JobSearchService
from ai_internship_assistant.services.lever import (
    LeverCompanyConfig,
    LeverHttpClient,
    LeverJobSource,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "lever"


def _fixture(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _query(
    role: str = "Cybersecurity Intern",
    *,
    location: str | None = None,
) -> JobSearchQuery:
    return JobSearchQuery(
        query_text=" ".join(part for part in [role, location] if part),
        role=role,
        location=location,
        employment_type=SearchEmploymentType.INTERNSHIP,
        priority=QueryPriority.HIGH,
        reason="Lever adapter test.",
        max_results=25,
    )


def _company(slug: str = "example") -> LeverCompanyConfig:
    return LeverCompanyConfig(
        company_name="Example Tech Company",
        company_slug=slug,
        base_url=f"https://jobs.lever.co/{slug}",
        tags=["software", "cybersecurity", "internship"],
    )


def _source(transport: httpx.MockTransport) -> LeverJobSource:
    client = httpx.Client(transport=transport)
    return LeverJobSource([_company()], http_client=LeverHttpClient(client=client))


def test_successful_lever_response() -> None:
    """A valid public Lever response should produce standardized matching jobs."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["mode"] == "json"
        assert request.headers["Accept"] == "application/json"
        assert "AI-Internship-Application-Assistant" in request.headers["User-Agent"]
        return httpx.Response(200, json=_fixture("postings_success.json"))

    jobs = _source(httpx.MockTransport(handler)).search(_query())

    assert [job.title for job in jobs] == ["Cybersecurity Intern"]


def test_empty_lever_response() -> None:
    """A valid empty Lever site should return no jobs and no errors."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_empty.json"))
        )
    )
    query = _query()

    assert source.search(query) == []
    assert source.errors_for_query(query) == []


def test_invalid_json_records_parsing_error() -> None:
    """Invalid JSON should become a structured parsing error."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"not-json",
                headers={"Content-Type": "application/json"},
            )
        )
    )
    query = _query()

    assert source.search(query) == []
    assert source.errors_for_query(query)[0].error_type == JobSearchErrorType.PARSING


def test_404_company_slug_records_error() -> None:
    """Invalid company slugs should produce non-recoverable response errors."""

    source = _source(httpx.MockTransport(lambda request: httpx.Response(404)))
    query = _query()

    source.search(query)
    error = source.errors_for_query(query)[0]

    assert error.error_type == JobSearchErrorType.INVALID_RESPONSE
    assert not error.recoverable


def test_429_rate_limit_records_recoverable_error() -> None:
    """Rate limiting should be respected and represented as recoverable."""

    source = _source(httpx.MockTransport(lambda request: httpx.Response(429)))
    query = _query()

    source.search(query)
    error = source.errors_for_query(query)[0]

    assert error.error_type == JobSearchErrorType.RATE_LIMIT
    assert error.recoverable


def test_timeout_records_network_error() -> None:
    """Timeouts should produce recoverable network errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Lever timed out", request=request)

    source = _source(httpx.MockTransport(handler))
    query = _query()

    source.search(query)
    error = source.errors_for_query(query)[0]

    assert error.error_type == JobSearchErrorType.NETWORK
    assert error.recoverable


def test_matching_cybersecurity_internship() -> None:
    """Cybersecurity queries should match relevant Lever postings."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_success.json"))
        )
    )

    jobs = source.search(_query("Cybersecurity Intern", location="Raleigh, NC"))

    assert [job.title for job in jobs] == ["Cybersecurity Intern"]


def test_matching_software_engineering_internship() -> None:
    """Software queries should match relevant remote Lever postings."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_success.json"))
        )
    )

    jobs = source.search(_query("Software Engineering Intern"))

    assert [job.title for job in jobs] == ["Software Engineering Intern"]


def test_non_matching_senior_role_is_filtered_out() -> None:
    """Early-career queries should exclude senior Lever roles."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_success.json"))
        )
    )

    jobs = source.search(_query("Security Intern"))

    assert "Senior Security Engineer" not in {job.title for job in jobs}


def test_remote_and_hybrid_workplace_classification() -> None:
    """Lever workplaceType should map to standardized work arrangements."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_success.json"))
        )
    )

    software_job = source.search(_query("Software Engineering Intern"))[0]
    security_job = source.search(_query("Cybersecurity Intern"))[0]

    assert software_job.work_arrangement == WorkArrangement.REMOTE
    assert security_job.work_arrangement == WorkArrangement.HYBRID


def test_internship_classification_from_title() -> None:
    """An internship title should classify as internship when commitment is missing."""

    posting = _fixture("postings_missing_optional.json")
    source = _source(httpx.MockTransport(lambda request: httpx.Response(200, json=posting)))

    job = source.search(_query("Software Intern"))[0]

    assert job.employment_type == EmploymentType.INTERNSHIP


def test_internship_classification_from_commitment() -> None:
    """Lever commitment should classify internship even without internship in title."""

    posting = _fixture("postings_missing_optional.json")
    posting[0]["text"] = "Software Student Program"
    source = _source(httpx.MockTransport(lambda request: httpx.Response(200, json=posting)))

    job = source.search(_query("Software Intern"))[0]

    assert job.employment_type == EmploymentType.INTERNSHIP


def test_job_posting_normalization_and_raw_data_preservation() -> None:
    """Lever fields should normalize while preserving the full provider payload."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_success.json"))
        )
    )

    job = source.search(_query("Cybersecurity Intern"))[0]

    assert job.source == JobSourceType.LEVER
    assert job.source_name == "Lever"
    assert job.company == "Example Tech Company"
    assert job.location == "Raleigh, NC"
    assert str(job.source_url) == "https://jobs.lever.co/example/lever-security-1"
    assert str(job.apply_url) == "https://jobs.lever.co/example/lever-security-1/apply"
    assert job.description == (
        "Join the security operations team and support network security monitoring."
    )
    assert job.responsibilities == [
        "Assist with security alert triage.",
        "Document investigation findings.",
    ]
    assert job.requirements == ["Knowledge of Linux and networking."]
    assert job.preferred_qualifications == ["Security+ certification."]
    assert job.salary_min == 50000
    assert job.salary_max == 65000
    assert job.posted_date is not None
    assert job.raw_data["lever"]["id"] == "lever-security-1"
    assert job.raw_data["company_slug"] == "example"


def test_multiple_company_configs_allow_partial_success() -> None:
    """One failed Lever site should not erase jobs from another site."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/bad"):
            return httpx.Response(404)
        return httpx.Response(200, json=_fixture("postings_success.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = LeverJobSource(
        [_company("bad"), _company("good")],
        http_client=LeverHttpClient(client=client),
    )
    query = _query()
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService([source]).search_all(query_set)

    assert [job.title for job in result.jobs] == ["Cybersecurity Intern"]
    assert len(result.errors) == 1
    assert result.errors[0].source_name == "Lever:bad"


def test_missing_optional_lever_fields_are_handled() -> None:
    """Missing optional provider fields should not prevent normalization."""

    source = _source(
        httpx.MockTransport(
            lambda request: httpx.Response(200, json=_fixture("postings_missing_optional.json"))
        )
    )

    job = source.search(_query("Software Intern"))[0]

    assert job.title == "Software Intern"
    assert job.location is None
    assert job.apply_url == job.source_url
    assert job.description is None
    assert job.responsibilities == []
    assert job.work_arrangement == WorkArrangement.UNKNOWN

