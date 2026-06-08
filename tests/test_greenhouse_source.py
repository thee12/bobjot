"""Tests for the public Greenhouse Job Board API adapter."""

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
from ai_internship_assistant.services.greenhouse import (
    GreenhouseCompanyConfig,
    GreenhouseHttpClient,
    GreenhouseJobSource,
)
from ai_internship_assistant.services.job_sources import JobSearchService

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "greenhouse"


def _fixture(name: str) -> dict[str, object]:
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
        reason="Greenhouse adapter test.",
        max_results=25,
    )


def _company(token: str = "example") -> GreenhouseCompanyConfig:  # noqa: S107
    return GreenhouseCompanyConfig(
        company_name="Example Security Company",
        board_token=token,
        base_url=f"https://boards.greenhouse.io/{token}",
        tags=["cybersecurity", "software", "internship"],
    )


def _source(handler: httpx.MockTransport) -> GreenhouseJobSource:
    client = httpx.Client(transport=handler)
    return GreenhouseJobSource(
        [_company()],
        http_client=GreenhouseHttpClient(client=client),
    )


def test_successful_greenhouse_response() -> None:
    """A valid public response should produce standardized matching jobs."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["content"] == "true"
        assert "AI-Internship-Application-Assistant" in request.headers["User-Agent"]
        return httpx.Response(200, json=_fixture("jobs_success.json"))

    jobs = _source(httpx.MockTransport(handler)).search(_query())

    assert [job.title for job in jobs] == ["Cybersecurity Intern"]


def test_empty_greenhouse_response() -> None:
    """A valid empty board should return no jobs and no source error."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_empty.json")))
    )

    assert source.search(_query()) == []
    assert source.errors_for_query(_query()) == []


def test_invalid_json_records_invalid_response_error() -> None:
    """Invalid JSON should become a structured board error."""

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


def test_404_board_not_found_records_error() -> None:
    """Invalid board tokens should produce non-recoverable invalid-response errors."""

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
        raise httpx.ReadTimeout("Greenhouse timed out", request=request)

    source = _source(httpx.MockTransport(handler))
    query = _query()

    source.search(query)
    error = source.errors_for_query(query)[0]

    assert error.error_type == JobSearchErrorType.NETWORK
    assert error.recoverable


def test_matching_cybersecurity_internship() -> None:
    """Cybersecurity queries should match relevant security internship content."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_success.json")))
    )

    jobs = source.search(_query("Cybersecurity Intern", location="Raleigh, NC"))

    assert [job.title for job in jobs] == ["Cybersecurity Intern"]


def test_matching_software_engineering_internship() -> None:
    """Software engineering queries should match relevant public postings."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_success.json")))
    )

    jobs = source.search(_query("Software Engineering Intern"))

    assert [job.title for job in jobs] == ["Software Engineering Intern"]


def test_non_matching_senior_role_is_filtered_out() -> None:
    """Early-career queries should exclude senior roles."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_success.json")))
    )

    jobs = source.search(_query("Security Intern"))

    assert "Senior Security Engineer" not in {job.title for job in jobs}


def test_remote_and_internship_classification() -> None:
    """Greenhouse text should support conservative arrangement and internship detection."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_success.json")))
    )

    job = source.search(_query("Software Engineering Intern"))[0]

    assert job.work_arrangement == WorkArrangement.REMOTE
    assert job.employment_type == EmploymentType.INTERNSHIP


def test_job_posting_normalization_and_raw_data_preservation() -> None:
    """Normalized postings should retain provider payloads and public URLs."""

    source = _source(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_fixture("jobs_success.json")))
    )

    job = source.search(_query("Cybersecurity Intern"))[0]

    assert job.source == JobSourceType.GREENHOUSE
    assert job.source_name == "Greenhouse"
    assert job.company == "Example Security Company"
    assert job.location == "Raleigh, NC"
    assert str(job.apply_url) == "https://boards.greenhouse.io/example/jobs/1001"
    assert job.description == (
        "Join our security operations team as a cybersecurity intern. "
        "Work with Linux and network security monitoring."
    )
    assert job.posted_date is not None
    assert job.raw_data["greenhouse"]["id"] == 1001
    assert job.raw_data["board_token"] == "example"  # noqa: S105 - public board identifier


def test_multiple_company_configs_allow_partial_success() -> None:
    """One failed board should not erase jobs from another configured board."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "/bad/" in request.url.path:
            return httpx.Response(404)
        return httpx.Response(200, json=_fixture("jobs_success.json"))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    source = GreenhouseJobSource(
        [_company("bad"), _company("good")],
        http_client=GreenhouseHttpClient(client=client),
    )
    query = _query()
    query_set = JobSearchQuerySet(queries=[query], primary_queries=[query])

    result = JobSearchService([source]).search_all(query_set)

    assert [job.title for job in result.jobs] == ["Cybersecurity Intern"]
    assert len(result.errors) == 1
    assert result.errors[0].source_name == "Greenhouse:bad"
