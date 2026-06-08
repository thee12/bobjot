"""Provider-neutral job posting and source-search result models."""

import hashlib
import re
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SkipValidation, model_validator

from ai_internship_assistant.domain.models.job_search import (
    JobSearchQuery,
    JobSearchQuerySet,
)

_WHITESPACE_PATTERN = re.compile(r"\s+")


class JobSeniority(StrEnum):
    """Supported job seniority bands."""

    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    JUNIOR = "junior"
    MID_LEVEL = "mid_level"
    SENIOR = "senior"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    """Standardized employment types across job providers."""

    INTERNSHIP = "internship"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class WorkArrangement(StrEnum):
    """Standardized work arrangements across job providers."""

    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class JobSourceType(StrEnum):
    """Supported internal job-source identifiers."""

    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    COMPANY_PAGE = "company_page"
    MANUAL = "manual"
    MOCK = "mock"


class JobSearchErrorType(StrEnum):
    """Standardized errors produced by job source integrations."""

    NETWORK = "network"
    RATE_LIMIT = "rate_limit"
    PARSING = "parsing"
    AUTHENTICATION = "authentication"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


class JobPosting(BaseModel):
    """Standardized job posting returned by every job source.

    Provider-specific payloads should be preserved in ``raw_data`` while
    downstream modules consume the normalized fields. Identity helpers support
    future deduplication without implementing deduplication in this phase.
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(min_length=1)
    source: JobSourceType
    source_name: str = Field(min_length=1)
    source_url: HttpUrl | None = None
    apply_url: HttpUrl | None = None
    canonical_url: HttpUrl | None = None
    title: str = Field(min_length=1)
    company: str = Field(min_length=1)
    location: str | None = None
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    seniority: JobSeniority = JobSeniority.UNKNOWN
    work_arrangement: WorkArrangement = WorkArrangement.UNKNOWN
    description: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    requirements: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    posted_date: date | None = None
    discovered_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    raw_data: dict[str, Any] = Field(default_factory=dict)
    normalized_title: str = ""
    normalized_company: str = ""
    fingerprint: str = ""

    @model_validator(mode="after")
    def populate_normalized_identity(self) -> "JobPosting":
        """Normalize provider identity fields and populate a stable fingerprint."""

        title = self._clean_display_text(self.title)
        company = self._clean_display_text(self.company)
        location = self._clean_display_text(self.location) if self.location else None
        source_name = self._clean_display_text(self.source_name)
        canonical_url = self.canonical_url or self.apply_url or self.source_url

        normalized_title = self._normalize_identity_text(title)
        normalized_company = self._normalize_identity_text(company)
        fingerprint_input = "|".join(
            [
                normalized_company,
                normalized_title,
                self._normalize_identity_text(location or ""),
                str(canonical_url or ""),
            ]
        )

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "company", company)
        object.__setattr__(self, "location", location)
        object.__setattr__(self, "source_name", source_name)
        object.__setattr__(self, "canonical_url", canonical_url)
        object.__setattr__(self, "normalized_title", normalized_title)
        object.__setattr__(self, "normalized_company", normalized_company)
        object.__setattr__(
            self,
            "fingerprint",
            hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest(),
        )
        return self

    @staticmethod
    def normalize_employment_type(value: str | None) -> EmploymentType:
        """Normalize a provider employment-type label."""

        normalized = JobPosting._normalize_identity_text(value or "")
        mappings = {
            "intern": EmploymentType.INTERNSHIP,
            "internship": EmploymentType.INTERNSHIP,
            "full time": EmploymentType.FULL_TIME,
            "fulltime": EmploymentType.FULL_TIME,
            "part time": EmploymentType.PART_TIME,
            "parttime": EmploymentType.PART_TIME,
            "contract": EmploymentType.CONTRACT,
            "contractor": EmploymentType.CONTRACT,
            "temporary": EmploymentType.TEMPORARY,
            "temp": EmploymentType.TEMPORARY,
        }
        return mappings.get(normalized, EmploymentType.UNKNOWN)

    @staticmethod
    def normalize_work_arrangement(value: str | None) -> WorkArrangement:
        """Normalize a provider work-arrangement label."""

        normalized = JobPosting._normalize_identity_text(value or "")
        if "remote" in normalized:
            return WorkArrangement.REMOTE
        if "hybrid" in normalized:
            return WorkArrangement.HYBRID
        if normalized in {"onsite", "on site", "in office", "office"}:
            return WorkArrangement.ONSITE
        return WorkArrangement.UNKNOWN

    @staticmethod
    def _clean_display_text(value: str) -> str:
        return _WHITESPACE_PATTERN.sub(" ", value).strip()

    @staticmethod
    def _normalize_identity_text(value: str) -> str:
        cleaned = _WHITESPACE_PATTERN.sub(" ", value).strip().casefold()
        return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


class NormalizedJobPosting(BaseModel):
    """Non-mutating normalized representation used for deduplication."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    original_job: SkipValidation[JobPosting]
    normalized_title: str
    normalized_company: str
    normalized_location: str
    normalized_employment_type: EmploymentType
    normalized_work_arrangement: WorkArrangement
    normalized_apply_url: str | None = None
    normalized_source_url: str | None = None
    normalized_description_text: str
    fingerprint: str
    similarity_keys: list[str] = Field(default_factory=list)


class JobDeduplicationGroup(BaseModel):
    """Traceable group containing a selected canonical job and duplicates."""

    model_config = ConfigDict(extra="forbid")

    canonical_job: SkipValidation[JobPosting]
    duplicate_jobs: list[SkipValidation[JobPosting]] = Field(default_factory=list)
    duplicate_count: int = 0
    confidence_score: float = Field(ge=0.0, le=1.0)
    reason: str

    @model_validator(mode="after")
    def populate_duplicate_count(self) -> "JobDeduplicationGroup":
        """Populate duplicate count from preserved original jobs."""

        object.__setattr__(self, "duplicate_count", len(self.duplicate_jobs))
        return self


class JobDeduplicationResult(BaseModel):
    """Result of conservative job deduplication."""

    model_config = ConfigDict(extra="forbid")

    unique_jobs: list[SkipValidation[JobPosting]] = Field(default_factory=list)
    duplicate_groups: list[JobDeduplicationGroup] = Field(default_factory=list)
    original_count: int = 0
    unique_count: int = 0
    duplicate_count: int = 0
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def populate_counts(self) -> "JobDeduplicationResult":
        """Populate counts from the deduplication output."""

        unique_count = len(self.unique_jobs)
        duplicate_count = sum(group.duplicate_count for group in self.duplicate_groups)
        object.__setattr__(self, "unique_count", unique_count)
        object.__setattr__(self, "duplicate_count", duplicate_count)
        return self


class JobSourceError(BaseModel):
    """Structured error from one job source and query."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source_name: str = Field(min_length=1)
    query_text: str
    error_type: JobSearchErrorType
    message: str = Field(min_length=1)
    recoverable: bool = True


class JobSourceSearchResult(BaseModel):
    """Result from one source for one search query."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    query: JobSearchQuery
    source_name: str = Field(min_length=1)
    jobs: list[JobPosting] = Field(default_factory=list)
    total_found: int = Field(default=0, ge=0)
    errors: list[JobSourceError] = Field(default_factory=list)
    searched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def populate_total_found(self) -> "JobSourceSearchResult":
        """Populate the job count from standardized results."""

        object.__setattr__(self, "total_found", len(self.jobs))
        return self


class JobSearchResultSet(BaseModel):
    """Aggregate partial-failure-safe results for a query set across sources."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    query_set: JobSearchQuerySet
    source_results: list[JobSourceSearchResult] = Field(default_factory=list)
    jobs: list[JobPosting] = Field(default_factory=list)
    normalized_jobs: list[NormalizedJobPosting] = Field(default_factory=list)
    deduplication_result: JobDeduplicationResult | None = None
    errors: list[JobSourceError] = Field(default_factory=list)
    total_found: int = Field(default=0, ge=0)
    searched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def populate_total_found(self) -> "JobSearchResultSet":
        """Populate the aggregate job count without deduplicating jobs yet."""

        object.__setattr__(self, "total_found", len(self.jobs))
        return self
