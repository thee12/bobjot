"""Typed runtime settings for the application.

Future entrypoints should depend on this module instead of reading environment
variables directly. Keeping settings centralized makes tests and deployments
predictable as the system grows.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_prefix="AI_INTERNSHIP_ASSISTANT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: str = Field(default="local", description="Runtime environment name.")
    database_url: str = Field(
        default="sqlite:///data/applications.db",
        description="Database connection URL for application tracking.",
    )
    log_level: str = Field(default="INFO", description="Application logging level.")

