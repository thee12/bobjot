"""Job source contracts, development mocks, and source orchestration.

Future Greenhouse, Lever, and company-career-page integrations should implement
``JobSource`` and convert provider responses into standardized ``JobPosting``
objects. Downstream modules should never depend on provider-specific payloads.

No real HTTP requests, scraping, or browser automation are implemented here.
"""

import hashlib
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import TypedDict

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobPosting,
    JobSearchErrorType,
    JobSearchQuery,
    JobSearchQuerySet,
    JobSearchResultSet,
    JobSourceError,
    JobSourceSearchResult,
    JobSourceType,
    SearchEmploymentType,
    WorkArrangement,
)


class MockJobTemplate(TypedDict):
    """Typed development-only mock posting template."""

    title: str
    company: str
    description: str
    technologies: list[str]


class JobSourceSearchError(RuntimeError):
    """Expected recoverable or non-recoverable failure from one job source."""

    def __init__(
        self,
        message: str,
        *,
        error_type: JobSearchErrorType = JobSearchErrorType.UNKNOWN,
        recoverable: bool = True,
    ) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.recoverable = recoverable


class JobSource(ABC):
    """Provider-neutral contract for future job-source integrations."""

    @property
    @abstractmethod
    def source_name(self) -> str:
        """Return a stable display name for this source."""

    @property
    @abstractmethod
    def source_type(self) -> JobSourceType:
        """Return the standardized internal source type."""

    @abstractmethod
    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        """Search one source and return standardized job postings."""


class MockJobSource(JobSource):
    """Development-only source returning realistic fake standardized jobs.

    This source performs no network requests. It exists exclusively for tests,
    local development, and exercising downstream workflows before real source
    integrations are implemented.
    """

    _DEFAULT_TEMPLATES: list[MockJobTemplate] = [
        {
            "title": "Cybersecurity Intern",
            "company": "Example Security Company",
            "description": "Support security monitoring and document investigation findings.",
            "technologies": ["Python", "Linux"],
        },
        {
            "title": "SOC Analyst Intern",
            "company": "Example Security Operations",
            "description": "Assist analysts with alert triage and security operations.",
            "technologies": ["Linux", "Networking"],
        },
        {
            "title": "Software Engineering Intern",
            "company": "Example Software Company",
            "description": "Build and test application features with the engineering team.",
            "technologies": ["Python", "Git"],
        },
        {
            "title": "Network Engineering Intern",
            "company": "Example Network Company",
            "description": "Support network operations and infrastructure documentation.",
            "technologies": ["Networking", "Cisco"],
        },
    ]

    def __init__(
        self,
        *,
        name: str = "Mock Job Source",
        templates: Sequence[MockJobTemplate] | None = None,
    ) -> None:
        self._name = name
        self._templates = list(templates or self._DEFAULT_TEMPLATES)

    @property
    def source_name(self) -> str:
        """Return the mock source display name."""

        return self._name

    @property
    def source_type(self) -> JobSourceType:
        """Return the mock source identifier."""

        return JobSourceType.MOCK

    def search(self, query: JobSearchQuery) -> list[JobPosting]:
        """Return fake jobs whose titles overlap the requested role."""

        if not query.query_text.strip() or not query.role.strip():
            return []

        jobs: list[JobPosting] = []
        query_terms = self._significant_terms(query.role)
        for template in self._templates:
            title = template["title"]
            title_terms = self._significant_terms(title)
            if not query_terms.intersection(title_terms):
                continue

            company = template["company"]
            identifier = hashlib.sha256(
                f"{self.source_name}|{company}|{title}".encode()
            ).hexdigest()[:16]
            source_url = f"https://example.test/jobs/{identifier}"
            jobs.append(
                JobPosting(
                    id=identifier,
                    source=self.source_type,
                    source_name=self.source_name,
                    source_url=source_url,
                    apply_url=f"{source_url}/apply",
                    title=title,
                    company=company,
                    location=query.location or ("Remote" if query.remote else "United States"),
                    employment_type=self._employment_type(query.employment_type),
                    work_arrangement=self._work_arrangement(query),
                    description=template["description"],
                    technologies=template["technologies"],
                    raw_data={"development_mock": True, "query": query.query_text},
                )
            )

        return jobs[: query.max_results]

    def _employment_type(self, value: SearchEmploymentType) -> EmploymentType:
        mappings = {
            SearchEmploymentType.INTERNSHIP: EmploymentType.INTERNSHIP,
            SearchEmploymentType.FULL_TIME: EmploymentType.FULL_TIME,
            SearchEmploymentType.PART_TIME: EmploymentType.PART_TIME,
            SearchEmploymentType.CONTRACT: EmploymentType.CONTRACT,
            SearchEmploymentType.ENTRY_LEVEL: EmploymentType.FULL_TIME,
        }
        return mappings[value]

    def _work_arrangement(self, query: JobSearchQuery) -> WorkArrangement:
        if query.remote:
            return WorkArrangement.REMOTE
        if query.hybrid:
            return WorkArrangement.HYBRID
        return WorkArrangement.ONSITE

    def _significant_terms(self, value: str) -> set[str]:
        ignored = {"entry", "level", "intern", "internship", "engineering", "analyst"}
        return {
            term
            for term in JobPosting._normalize_identity_text(value).split()
            if term not in ignored
        }


class JobSearchService:
    """Run query sets across job sources while preserving partial successes."""

    def __init__(self, sources: Sequence[JobSource]) -> None:
        self._sources = list(sources)

    def search_all(self, query_set: JobSearchQuerySet) -> JobSearchResultSet:
        """Search every configured source for every query.

        Expected ``JobSourceSearchError`` failures become structured errors.
        Other exceptions are programmer or integration bugs and intentionally
        propagate instead of being silently converted to unknown failures.
        """

        source_results: list[JobSourceSearchResult] = []
        jobs: list[JobPosting] = []
        errors: list[JobSourceError] = []

        for source in self._sources:
            for query in query_set.queries:
                try:
                    source_jobs = source.search(query)
                    result_errors: list[JobSourceError] = []
                except JobSourceSearchError as exc:
                    source_jobs = []
                    source_error = JobSourceError(
                        source_name=source.source_name,
                        query_text=query.query_text,
                        error_type=exc.error_type,
                        message=str(exc),
                        recoverable=exc.recoverable,
                    )
                    result_errors = [source_error]
                    errors.append(source_error)

                jobs.extend(source_jobs)
                source_results.append(
                    JobSourceSearchResult(
                        query=query,
                        source_name=source.source_name,
                        jobs=source_jobs,
                        errors=result_errors,
                    )
                )

        return JobSearchResultSet(
            query_set=query_set,
            source_results=source_results,
            jobs=jobs,
            errors=errors,
        )
