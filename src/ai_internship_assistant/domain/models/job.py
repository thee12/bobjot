"""Job posting models used by discovery and analysis workflows."""

from enum import StrEnum

from pydantic import BaseModel, Field, HttpUrl


class JobSeniority(StrEnum):
    """Supported seniority bands for this product."""

    INTERNSHIP = "internship"
    ENTRY_LEVEL = "entry_level"
    UNKNOWN = "unknown"


class EmploymentType(StrEnum):
    """Common employment types for early-career roles."""

    INTERNSHIP = "internship"
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CONTRACT = "contract"
    UNKNOWN = "unknown"


class JobPosting(BaseModel):
    """Normalized job posting metadata collected from a source website."""

    title: str
    company: str
    source_url: HttpUrl | None = None
    location: str | None = None
    seniority: JobSeniority = JobSeniority.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    description_text: str | None = None
    discovered_at: str | None = Field(default=None, description="ISO timestamp when collected.")

