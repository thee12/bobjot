"""Public Greenhouse Job Board API integration.

This adapter uses only unauthenticated public Greenhouse Job Board GET
endpoints. It does not submit applications, bypass authentication, scrape
logged-in pages, automate browsers, or evade rate limits.
"""

import json
import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from ai_internship_assistant.domain.models import (
    JobPosting,
    JobSearchErrorType,
    JobSearchQuery,
    JobSourceError,
    JobSourceType,
)
from ai_internship_assistant.services.job_source_utils import (
    detect_employment_type,
    detect_work_arrangement,
    matches_query,
    plain_text_from_html,
)
from ai_internship_assistant.services.job_sources import JobSource

_DEFAULT_API_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
_DEFAULT_USER_AGENT = "AI-Internship-Application-Assistant/0.1 (+public-job-discovery)"


class GreenhouseCompanyConfig(BaseModel):
    """Configuration for one public Greenhouse company board."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    company_name: str = Field(min_length=1)
    board_token: str = Field(min_length=1)
    base_url: HttpUrl | None = None
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


DEFAULT_GREENHOUSE_COMPANIES = [
    GreenhouseCompanyConfig(
        company_name="Example Greenhouse Company",
        board_token="replace-with-public-board-token",  # noqa: S106 - public board identifier
        base_url="https://boards.greenhouse.io/replace-with-public-board-token",
        enabled=False,
        tags=["example", "disabled"],
    )
]


class GreenhouseHttpClient:
    """Thin polite HTTP wrapper for public Greenhouse board requests."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        timeout_seconds: float = 10.0,
        user_agent: str = _DEFAULT_USER_AGENT,
        api_base_url: str = _DEFAULT_API_BASE_URL,
    ) -> None:
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout_seconds,
            headers={"User-Agent": user_agent},
        )
        self._api_base_url = api_base_url.rstrip("/")
        self._user_agent = user_agent
        self._timeout_seconds = timeout_seconds

    def fetch_jobs(self, board_token: str) -> dict[str, Any]:
        """Fetch public jobs with descriptions, departments, and offices."""

        response = self._client.get(
            f"{self._api_base_url}/{board_token}/jobs",
            params={"content": "true"},
            headers={"User-Agent": self._user_agent},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            msg = "Greenhouse response did not contain a jobs list"
            raise ValueError(msg)
        return payload

    def close(self) -> None:
        """Close an internally owned HTTP client."""

        if self._owns_client:
            self._client.close()


class GreenhouseJobSource(JobSource):
    """Search configured public Greenhouse boards and normalize matching jobs."""

    def __init__(
        self,
        companies: Sequence[GreenhouseCompanyConfig] | None = None,
        *,
        http_client: GreenhouseHttpClient | None = None,
        request_delay_seconds: float = 0.0,
    ) -> None:
        self._companies = list(companies or DEFAULT_GREENHOUSE_COMPANIES)
        self._http_client = http_client or GreenhouseHttpClient()
        self._request_delay_seconds = max(request_delay_seconds, 0.0)
        self._errors_by_query: dict[str, list[JobSourceError]] = {}

    @property
    def source_name(self) -> str:
        """Return the standardized source display name."""

        return "Greenhouse"

    @property
    def source_type(self) -> JobSourceType:
        """Return the standardized Greenhouse source identifier."""

        return JobSourceType.GREENHOUSE

    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        """Search enabled public Greenhouse boards for matching postings."""

        self._errors_by_query[query.query_text] = []
        if not query.query_text.strip() or not query.role.strip():
            return []

        jobs: list[JobPosting] = []
        enabled_companies = [company for company in self._companies if company.enabled]
        for index, company in enumerate(enabled_companies):
            if index > 0 and self._request_delay_seconds:
                time.sleep(self._request_delay_seconds)
            try:
                payload = self._http_client.fetch_jobs(company.board_token)
                jobs.extend(self._matching_jobs(company, payload["jobs"], query))
            except httpx.TimeoutException as exc:
                self._record_error(company, query, JobSearchErrorType.NETWORK, str(exc), True)
            except httpx.HTTPStatusError as exc:
                self._record_http_error(company, query, exc)
            except json.JSONDecodeError as exc:
                self._record_error(
                    company,
                    query,
                    JobSearchErrorType.PARSING,
                    str(exc),
                    False,
                )
            except (ValueError, TypeError) as exc:
                self._record_error(
                    company,
                    query,
                    JobSearchErrorType.INVALID_RESPONSE,
                    str(exc),
                    False,
                )
            except httpx.RequestError as exc:
                self._record_error(company, query, JobSearchErrorType.NETWORK, str(exc), True)

        return jobs[: query.max_results]

    def errors_for_query(self, query: JobSearchQuery) -> list[JobSourceError]:
        """Return per-board errors recorded during the latest query search."""

        return list(self._errors_by_query.get(query.query_text, []))

    def _matching_jobs(
        self,
        company: GreenhouseCompanyConfig,
        raw_jobs: object,
        query: JobSearchQuery,
    ) -> list[JobPosting]:
        if not isinstance(raw_jobs, list):
            msg = "Greenhouse jobs payload must be a list"
            raise ValueError(msg)

        jobs: list[JobPosting] = []
        for raw_job in raw_jobs:
            if not isinstance(raw_job, dict):
                continue
            if self._matches(raw_job, query):
                jobs.append(self._normalize_job(company, raw_job))
        return jobs

    def _matches(self, raw_job: dict[str, Any], query: JobSearchQuery) -> bool:
        title = str(raw_job.get("title", ""))
        description = self._description_text(str(raw_job.get("content", "")))
        departments = self._names(raw_job.get("departments"))
        offices = self._names(raw_job.get("offices"))
        location = self._location_name(raw_job)
        arrangement = detect_work_arrangement(title, location, description)
        return matches_query(
            query=query,
            title=title,
            searchable_values=[title, description, *departments, *offices, location],
            location_values=[location, *offices],
            work_arrangement=arrangement,
        )

    def _normalize_job(
        self,
        company: GreenhouseCompanyConfig,
        raw_job: dict[str, Any],
    ) -> JobPosting:
        title = str(raw_job.get("title", "Untitled Greenhouse Job"))
        location = self._location_name(raw_job)
        description = self._description_text(str(raw_job.get("content", "")))
        absolute_url = str(raw_job.get("absolute_url", company.base_url or ""))
        departments = self._names(raw_job.get("departments"))
        offices = self._names(raw_job.get("offices"))
        posted_date = self._updated_date(raw_job.get("updated_at"))

        return JobPosting(
            id=str(raw_job.get("id", f"{company.board_token}:{title}")),
            source=self.source_type,
            source_name=self.source_name,
            source_url=absolute_url or None,
            apply_url=absolute_url or None,
            title=title,
            company=company.company_name,
            location=location or None,
            employment_type=detect_employment_type(title, description),
            work_arrangement=detect_work_arrangement(title, location, description),
            description=description or None,
            posted_date=posted_date,
            raw_data={
                "greenhouse": raw_job,
                "board_token": company.board_token,
                "company_tags": company.tags,
                "departments": departments,
                "offices": offices,
            },
        )

    def _record_http_error(
        self,
        company: GreenhouseCompanyConfig,
        query: JobSearchQuery,
        error: httpx.HTTPStatusError,
    ) -> None:
        status_code = error.response.status_code
        if status_code == 429:
            error_type = JobSearchErrorType.RATE_LIMIT
            recoverable = True
        elif status_code == 404:
            error_type = JobSearchErrorType.INVALID_RESPONSE
            recoverable = False
        elif status_code in {401, 403}:
            error_type = JobSearchErrorType.AUTHENTICATION
            recoverable = False
        else:
            error_type = JobSearchErrorType.NETWORK
            recoverable = status_code >= 500
        self._record_error(
            company,
            query,
            error_type,
            f"Greenhouse board '{company.board_token}' returned HTTP {status_code}",
            recoverable,
        )

    def _record_error(
        self,
        company: GreenhouseCompanyConfig,
        query: JobSearchQuery,
        error_type: JobSearchErrorType,
        message: str,
        recoverable: bool,
    ) -> None:
        self._errors_by_query[query.query_text].append(
            JobSourceError(
                source_name=f"{self.source_name}:{company.board_token}",
                query_text=query.query_text,
                error_type=error_type,
                message=message or error_type.value,
                recoverable=recoverable,
            )
        )

    def _location_name(self, raw_job: dict[str, Any]) -> str:
        location = raw_job.get("location")
        if isinstance(location, dict):
            return str(location.get("name", "")).strip()
        return ""

    def _names(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            str(item.get("name", "")).strip()
            for item in value
            if isinstance(item, dict) and item.get("name")
        ]

    def _description_text(self, content: str) -> str:
        return plain_text_from_html(content)

    def _updated_date(self, value: object) -> date | None:
        if not isinstance(value, str):
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            return None
