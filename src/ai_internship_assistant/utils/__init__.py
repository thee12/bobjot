"""Reusable utility helpers for application services."""

from ai_internship_assistant.utils.normalization import normalize_skill_name
from ai_internship_assistant.utils.skill_matching import (
    RELATED_SKILLS,
    SKILL_ALIASES,
    canonical_skill_name,
    deduplicate_match_terms,
    normalize_match_term,
    related_job_terms,
)

__all__ = [
    "RELATED_SKILLS",
    "SKILL_ALIASES",
    "canonical_skill_name",
    "deduplicate_match_terms",
    "normalize_match_term",
    "normalize_skill_name",
    "related_job_terms",
]
