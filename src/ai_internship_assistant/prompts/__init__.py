"""Versioned prompt builders used by provider-backed services."""

from ai_internship_assistant.prompts.job_description_analysis import (
    JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION,
    JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT,
    build_job_description_analysis_prompt,
)

__all__ = [
    "JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION",
    "JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT",
    "build_job_description_analysis_prompt",
]
