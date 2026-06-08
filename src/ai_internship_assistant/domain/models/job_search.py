"""Structured models for deterministic job search query generation."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ai_internship_assistant.domain.models.candidate_profile import ExperienceLevel


class SearchEmploymentType(StrEnum):
    """Employment types supported by query generation."""

    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"


class RemotePreference(StrEnum):
    """Location-mode preference used when generating search queries."""

    UNSPECIFIED = "unspecified"
    REMOTE_ALLOWED = "remote_allowed"
    REMOTE_ONLY = "remote_only"
    HYBRID_ALLOWED = "hybrid_allowed"
    HYBRID_ONLY = "hybrid_only"
    ONSITE_ONLY = "onsite_only"


class QueryPriority(StrEnum):
    """Priority assigned to generated job-search queries."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class JobSearchPreferences(BaseModel):
    """User preferences that refine, but do not replace, candidate-profile evidence."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    desired_roles: list[str] = Field(default_factory=list)
    desired_locations: list[str] = Field(default_factory=list)
    remote_preference: RemotePreference = RemotePreference.UNSPECIFIED
    employment_types: list[SearchEmploymentType] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    preferred_companies: list[str] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    seniority_level: ExperienceLevel | None = None
    max_results_per_query: int = Field(default=25, ge=1, le=100)


class JobSearchQuery(BaseModel):
    """One structured query consumable by a future job source integration."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    query_text: str = Field(min_length=1)
    role: str = Field(min_length=1)
    location: str | None = None
    employment_type: SearchEmploymentType
    remote: bool = False
    hybrid: bool = False
    priority: QueryPriority
    source_hint: str | None = None
    reason: str = Field(min_length=1)
    max_results: int = Field(ge=1, le=100)


class JobSearchQuerySet(BaseModel):
    """Structured query collection generated from a CandidateProfile."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    queries: list[JobSearchQuery] = Field(default_factory=list)
    primary_queries: list[JobSearchQuery] = Field(default_factory=list)
    secondary_queries: list[JobSearchQuery] = Field(default_factory=list)
    excluded_terms: list[str] = Field(default_factory=list)
    generated_from_profile: bool = True
    total_count: int = 0

    @model_validator(mode="after")
    def populate_total_count(self) -> "JobSearchQuerySet":
        """Populate the unique generated query count."""

        object.__setattr__(self, "total_count", len(self.queries))
        return self
