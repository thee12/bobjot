"""Public Lever Postings API integration.

This adapter uses only published public Lever posting GET endpoints. It does
not submit applications, use private APIs, access logged-in pages, use session
cookies, automate browsers, or evade rate limits.
"""

import json
import re
import time
from collections.abc import Sequence
from datetime import UTC, date, datetime
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

_DEFAULT_API_BASE_URL = "https://api.lever.co/v0/postings"
_DEFAULT_USER_AGENT = "AI-Internship-Application-Assistant/0.1 (+public-job-discovery)"


class LeverCompanyConfig(BaseModel):
    """Configuration for one public Lever company site."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    company_name: str = Field(min_length=1)
    company_slug: str = Field(min_length=1)
    base_url: HttpUrl | None = None
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


DEFAULT_LEVER_COMPANIES = [
    LeverCompanyConfig(
        company_name="Example Lever Company",
        company_slug="replace-with-public-company-slug",
        base_url="https://jobs.lever.co/replace-with-public-company-slug",
        enabled=False,
        tags=["example", "disabled"],
    )
]


class LeverHttpClient:
    """Thin polite HTTP wrapper for public Lever posting requests."""

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

    def fetch_jobs(self, company_slug: str) -> list[dict[str, Any]]:
        """Fetch published public Lever postings in JSON mode."""

        response = self._client.get(
            f"{self._api_base_url}/{company_slug}",
            params={"mode": "json"},
            headers={"User-Agent": self._user_agent, "Accept": "application/json"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            msg = "Lever response was not a postings list"
            raise ValueError(msg)
        return [posting for posting in payload if isinstance(posting, dict)]

    def close(self) -> None:
        """Close an internally owned HTTP client."""

        if self._owns_client:
            self._client.close()


class LeverJobSource(JobSource):
    """Search configured public Lever sites and normalize matching postings."""

    def __init__(
        self,
        companies: Sequence[LeverCompanyConfig] | None = None,
        *,
        http_client: LeverHttpClient | None = None,
        request_delay_seconds: float = 0.0,
    ) -> None:
        self._companies = list(companies or DEFAULT_LEVER_COMPANIES)
        self._http_client = http_client or LeverHttpClient()
        self._request_delay_seconds = max(request_delay_seconds, 0.0)
        self._errors_by_query: dict[str, list[JobSourceError]] = {}

    @property
    def source_name(self) -> str:
        """Return the standardized source display name."""

        return "Lever"

    @property
    def source_type(self) -> JobSourceType:
        """Return the standardized Lever source identifier."""

        return JobSourceType.LEVER

    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        """Search enabled public Lever sites for matching postings."""

        self._errors_by_query[query.query_text] = []
        if not query.query_text.strip() or not query.role.strip():
            return []

        jobs: list[JobPosting] = []
        enabled_companies = [company for company in self._companies if company.enabled]
        for index, company in enumerate(enabled_companies):
            if index > 0 and self._request_delay_seconds:
                time.sleep(self._request_delay_seconds)
            try:
                postings = self._http_client.fetch_jobs(company.company_slug)
                jobs.extend(self._matching_jobs(company, postings, query))
            except httpx.TimeoutException as exc:
                self._record_error(company, query, JobSearchErrorType.NETWORK, str(exc), True)
            except httpx.HTTPStatusError as exc:
                self._record_http_error(company, query, exc)
            except json.JSONDecodeError as exc:
                self._record_error(company, query, JobSearchErrorType.PARSING, str(exc), False)
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
        """Return per-site errors recorded during the latest query search."""

        return list(self._errors_by_query.get(query.query_text, []))

    def _matching_jobs(
        self,
        company: LeverCompanyConfig,
        postings: Sequence[dict[str, Any]],
        query: JobSearchQuery,
    ) -> list[JobPosting]:
        jobs: list[JobPosting] = []
        for posting in postings:
            if self._matches(posting, query):
                jobs.append(self._normalize_job(company, posting))
        return jobs

    def _matches(self, posting: dict[str, Any], query: JobSearchQuery) -> bool:
        title = self._string(posting.get("text"))
        categories = self._mapping(posting.get("categories"))
        location = self._string(categories.get("location"))
        team = self._string(categories.get("team"))
        department = self._string(categories.get("department"))
        commitment = self._string(categories.get("commitment"))
        workplace_type = self._string(posting.get("workplaceType"))
        description = self._description(posting)
        list_text = " ".join(self._list_contents(posting))
        arrangement = detect_work_arrangement(workplace_type, location, title, description)

        return matches_query(
            query=query,
            title=title,
            searchable_values=[
                title,
                location,
                team,
                department,
                commitment,
                workplace_type,
                description,
                list_text,
            ],
            location_values=[location, *self._all_locations(categories)],
            work_arrangement=arrangement,
        )

    def _normalize_job(
        self,
        company: LeverCompanyConfig,
        posting: dict[str, Any],
    ) -> JobPosting:
        categories = self._mapping(posting.get("categories"))
        title = self._string(posting.get("text")) or "Untitled Lever Job"
        location = self._string(categories.get("location"))
        commitment = self._string(categories.get("commitment"))
        workplace_type = self._string(posting.get("workplaceType"))
        description = self._description(posting)
        responsibilities, requirements, preferred = self._classified_lists(posting)
        hosted_url = self._string(posting.get("hostedUrl"))
        apply_url = self._string(posting.get("applyUrl"))
        salary_min, salary_max = self._salary_range(posting.get("salaryRange"))

        return JobPosting(
            id=self._string(posting.get("id")) or f"{company.company_slug}:{title}",
            source=self.source_type,
            source_name=self.source_name,
            source_url=hosted_url or None,
            apply_url=apply_url or hosted_url or None,
            title=title,
            company=company.company_name,
            location=location or None,
            employment_type=detect_employment_type(title, commitment, description),
            work_arrangement=detect_work_arrangement(
                workplace_type,
                location,
                title,
                description,
            ),
            description=description or None,
            responsibilities=responsibilities,
            requirements=requirements,
            preferred_qualifications=preferred,
            salary_min=salary_min,
            salary_max=salary_max,
            posted_date=self._created_date(posting.get("createdAt")),
            raw_data={
                "lever": posting,
                "company_slug": company.company_slug,
                "company_tags": company.tags,
                "team": self._string(categories.get("team")),
                "department": self._string(categories.get("department")),
                "commitment": commitment,
            },
        )

    def _description(self, posting: dict[str, Any]) -> str:
        content = self._mapping(posting.get("content"))
        candidates = [
            posting.get("descriptionPlain"),
            content.get("descriptionPlain"),
            posting.get("openingPlain"),
            posting.get("description"),
            content.get("description"),
        ]
        for candidate in candidates:
            value = self._string(candidate)
            if value:
                return plain_text_from_html(value)
        return ""

    def _list_contents(self, posting: dict[str, Any]) -> list[str]:
        content = self._mapping(posting.get("content"))
        raw_lists = posting.get("lists")
        if not isinstance(raw_lists, list):
            raw_lists = content.get("lists")
        if not isinstance(raw_lists, list):
            return []
        return [
            plain_text_from_html(self._string(item.get("content")))
            for item in raw_lists
            if isinstance(item, dict) and item.get("content")
        ]

    def _classified_lists(
        self,
        posting: dict[str, Any],
    ) -> tuple[list[str], list[str], list[str]]:
        content = self._mapping(posting.get("content"))
        raw_lists = posting.get("lists")
        if not isinstance(raw_lists, list):
            raw_lists = content.get("lists")
        if not isinstance(raw_lists, list):
            return [], [], []

        responsibilities: list[str] = []
        requirements: list[str] = []
        preferred: list[str] = []
        for item in raw_lists:
            if not isinstance(item, dict):
                continue
            heading = self._string(item.get("text")).casefold()
            values = self._html_list_items(self._string(item.get("content")))
            if any(term in heading for term in ("responsibil", "what you'll do", "you will")):
                responsibilities.extend(values)
            elif any(term in heading for term in ("preferred", "nice to have", "bonus")):
                preferred.extend(values)
            elif any(term in heading for term in ("require", "qualification", "what you bring")):
                requirements.extend(values)

        return responsibilities, requirements, preferred

    def _html_list_items(self, content: str) -> list[str]:
        if not content:
            return []
        items = re.findall(r"<li[^>]*>(.*?)</li>", content, flags=re.IGNORECASE | re.DOTALL)
        if items:
            return [plain_text_from_html(item) for item in items if plain_text_from_html(item)]
        plain = plain_text_from_html(content)
        return [plain] if plain else []

    def _all_locations(self, categories: dict[str, Any]) -> list[str]:
        values = categories.get("allLocations")
        if not isinstance(values, list):
            return []
        return [self._string(value) for value in values if self._string(value)]

    def _salary_range(self, value: object) -> tuple[float | None, float | None]:
        salary_range = self._mapping(value)
        return self._number(salary_range.get("min")), self._number(salary_range.get("max"))

    def _created_date(self, value: object) -> date | None:
        if isinstance(value, int | float):
            try:
                return datetime.fromtimestamp(value / 1000, tz=UTC).date()
            except (OverflowError, OSError, ValueError):
                return None
        return None

    def _record_http_error(
        self,
        company: LeverCompanyConfig,
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
            f"Lever site '{company.company_slug}' returned HTTP {status_code}",
            recoverable,
        )

    def _record_error(
        self,
        company: LeverCompanyConfig,
        query: JobSearchQuery,
        error_type: JobSearchErrorType,
        message: str,
        recoverable: bool,
    ) -> None:
        self._errors_by_query[query.query_text].append(
            JobSourceError(
                source_name=f"{self.source_name}:{company.company_slug}",
                query_text=query.query_text,
                error_type=error_type,
                message=message or error_type.value,
                recoverable=recoverable,
            )
        )

    def _mapping(self, value: object) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _string(self, value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _number(self, value: object) -> float | None:
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
        return None
