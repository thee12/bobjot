"""Versioned prompt builders used by provider-backed services."""

from ai_internship_assistant.prompts.job_description_analysis import (
    JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION,
    JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT,
    build_job_description_analysis_prompt,
)
from ai_internship_assistant.prompts.resume_bullet_rewrite import (
    BULLET_REWRITE_PROMPT_VERSION,
    BULLET_REWRITE_SYSTEM_PROMPT,
    build_bullet_rewrite_prompt,
)

__all__ = [
    "JOB_DESCRIPTION_ANALYSIS_PROMPT_VERSION",
    "JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT",
    "BULLET_REWRITE_PROMPT_VERSION",
    "BULLET_REWRITE_SYSTEM_PROMPT",
    "build_bullet_rewrite_prompt",
    "build_job_description_analysis_prompt",
]
