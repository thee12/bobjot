"""User preference models for matching roles to a candidate."""

from pydantic import BaseModel, Field


class UserPreferences(BaseModel):
    """Preferences used to guide job discovery and matching."""

    desired_titles: list[str] = Field(default_factory=list)
    preferred_locations: list[str] = Field(default_factory=list)
    remote_ok: bool = True
    industries: list[str] = Field(default_factory=list)
    excluded_companies: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)

