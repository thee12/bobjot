"""Shared deterministic helpers for public job-source adapters."""

import html
import re
from collections.abc import Iterable

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobPosting,
    JobSearchQuery,
    WorkArrangement,
)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")

INTERNSHIP_TERMS = (
    "intern",
    "internship",
    "co-op",
    "coop",
    "university program",
    "student program",
    "early talent",
)
SENIOR_TERMS = ("senior", "staff", "principal", "lead", "manager", "director", "architect")

_ROLE_EXPANSIONS: dict[str, set[str]] = {
    "cybersecurity": {"cybersecurity", "security", "soc", "information security"},
    "soc": {"soc", "security operations", "security analyst"},
    "software": {"software", "developer", "engineering"},
    "network": {"network", "networking", "infrastructure", "noc"},
    "cloud": {"cloud", "devops", "infrastructure"},
}


def role_terms(role: str) -> set[str]:
    """Return meaningful and domain-expanded terms for a requested role."""

    normalized_role = JobPosting._normalize_identity_text(role)
    ignored = {"entry", "level", "intern", "internship", "engineering", "analyst"}
    terms = {term for term in normalized_role.split() if term not in ignored}
    expanded = set(terms)
    for term in terms:
        expanded.update(_ROLE_EXPANSIONS.get(term, set()))
    return expanded


def location_terms(location: str) -> set[str]:
    """Return meaningful normalized terms for a requested location."""

    ignored = {"united", "states", "usa", "us"}
    return {
        term
        for term in JobPosting._normalize_identity_text(location).split()
        if term not in ignored
    }


def is_early_career_query(query: JobSearchQuery) -> bool:
    """Whether a query targets internship or entry-level work."""

    return query.employment_type.value in {"internship", "entry_level"}


def has_senior_title(title: str) -> bool:
    """Whether a title contains a clearly senior-level term."""

    normalized = title.casefold()
    return any(term in normalized for term in SENIOR_TERMS)


def detect_employment_type(*values: str) -> EmploymentType:
    """Classify employment type conservatively from provider text."""

    text = " ".join(values).casefold()
    if any(term in text for term in INTERNSHIP_TERMS):
        return EmploymentType.INTERNSHIP
    normalized = JobPosting._normalize_identity_text(text)
    for provider_value in ("full time", "part time", "contract", "temporary"):
        if provider_value in normalized:
            return JobPosting.normalize_employment_type(provider_value)
    return EmploymentType.UNKNOWN


def detect_work_arrangement(*values: str) -> WorkArrangement:
    """Classify work arrangement conservatively from provider text."""

    text = " ".join(values).casefold()
    if "hybrid" in text:
        return WorkArrangement.HYBRID
    if "remote" in text:
        return WorkArrangement.REMOTE
    if any(term in text for term in ("on-site", "onsite", "on site", "in-office", "in office")):
        return WorkArrangement.ONSITE
    return WorkArrangement.UNKNOWN


def plain_text_from_html(value: str) -> str:
    """Convert provider HTML fragments to readable plain text."""

    unescaped = html.unescape(html.unescape(value))
    without_tags = _HTML_TAG_PATTERN.sub(" ", unescaped)
    return _WHITESPACE_PATTERN.sub(" ", without_tags).strip()


def matches_query(
    *,
    query: JobSearchQuery,
    title: str,
    searchable_values: Iterable[str],
    location_values: Iterable[str],
    work_arrangement: WorkArrangement,
) -> bool:
    """Apply shared deterministic role/location/seniority filtering."""

    if is_early_career_query(query) and has_senior_title(title):
        return False

    searchable = " ".join(searchable_values).casefold()
    requested_role_terms = role_terms(query.role)
    if requested_role_terms and not any(term in searchable for term in requested_role_terms):
        return False

    if query.location and work_arrangement != WorkArrangement.REMOTE:
        requested_location_terms = location_terms(query.location)
        location_searchable = " ".join(location_values).casefold()
        if requested_location_terms and not all(
            term in location_searchable for term in requested_location_terms
        ):
            return False

    return True

