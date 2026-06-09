"""Typed runtime settings for the application.

Future entrypoints should depend on this module instead of reading environment
variables directly. Keeping settings centralized makes tests and deployments
predictable as the system grows.
"""

from pydantic import Field, SecretStr
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
    sqlite_file_path: str = Field(
        default="data/applications.db",
        description="Default local SQLite path when a direct path is useful.",
    )
    enable_persistence: bool = Field(
        default=True,
        description="Enable local persistence workflows.",
    )
    resume_output_dir: str = Field(
        default="generated_resumes",
        description="Private local output directory for generated resume files.",
    )
    log_level: str = Field(default="INFO", description="Application logging level.")
    openai_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OPENAI_API_KEY",
        description="OpenAI API key. Never commit this value.",
    )
    job_analysis_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model used for structured job-description analysis.",
    )
    job_analysis_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for LLM job analysis.",
    )
    job_analysis_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="OpenAI job-analysis request timeout.",
    )
    job_analysis_max_input_length: int = Field(
        default=30_000,
        ge=1_000,
        description="Maximum job-prompt input length before conservative truncation.",
    )
    enable_llm_analysis: bool = Field(
        default=False,
        description="Enable direct LLM job-description analysis.",
    )
    enable_hybrid_analysis: bool = Field(
        default=False,
        description="Enable rule-based plus LLM job-description analysis.",
    )
    bullet_rewrite_model: str = Field(
        default="gpt-4.1-mini",
        description="OpenAI model used for structured single-bullet rewriting.",
    )
    bullet_rewrite_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        description="Sampling temperature for bullet rewriting.",
    )
    bullet_rewrite_timeout_seconds: float = Field(
        default=30.0,
        gt=0.0,
        description="OpenAI bullet-rewrite request timeout.",
    )
