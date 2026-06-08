"""Tests for deterministic job search query generation."""

import re

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    CandidateProfile,
    ExperienceLevel,
    JobSearchPreferences,
    ProfileValidationStatus,
    QueryPriority,
    RemotePreference,
    SearchEmploymentType,
)
from ai_internship_assistant.services.job_search_query_generator import JobSearchQueryGenerator


def _profile(
    *,
    primary_domain: CandidateDomain,
    secondary_domains: list[CandidateDomain] | None = None,
    target_roles: list[str] | None = None,
    core_skills: list[str] | None = None,
    certifications: list[str] | None = None,
) -> CandidateProfile:
    """Build a candidate profile for query-generation tests."""

    return CandidateProfile(
        candidate_name="Example Candidate",
        experience_level=ExperienceLevel.STUDENT,
        primary_domain=primary_domain,
        secondary_domains=secondary_domains or [],
        core_skills=core_skills or [],
        supporting_skills=[],
        certifications=certifications or [],
        technologies=core_skills or [],
        target_roles=target_roles or [],
        industry_keywords=[primary_domain.value],
        search_keywords=[],
        education_level="Bachelor's",
        confidence_score=0.9,
        profile_summary="Example candidate profile.",
        validation_status=ProfileValidationStatus.CLEAN,
        validation_messages=[],
    )


def _normalized_queries(query_texts: list[str]) -> list[str]:
    return [re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip() for text in query_texts]


def test_cybersecurity_profile_without_preferences() -> None:
    """Cybersecurity profiles should receive strong role-oriented query variants."""

    profile = _profile(
        primary_domain=CandidateDomain.CYBERSECURITY,
        target_roles=["Cybersecurity Intern", "SOC Analyst Intern"],
        core_skills=["Python", "Linux", "Networking"],
        certifications=["Security+"],
    )

    result = JobSearchQueryGenerator().generate(profile)
    high_query_texts = {query.query_text for query in result.primary_queries}

    assert "Cybersecurity Intern" in high_query_texts
    assert "SOC Analyst Intern" in high_query_texts
    assert "Security Operations Intern" in high_query_texts
    assert result.total_count == len(result.queries)
    assert set(["Senior", "Staff", "Principal", "Lead"]).issubset(result.excluded_terms)
    assert all(query.reason for query in result.queries)


def test_cybersecurity_profile_with_raleigh_location() -> None:
    """Location preferences should be applied without inventing other locations."""

    profile = _profile(primary_domain=CandidateDomain.CYBERSECURITY)
    preferences = JobSearchPreferences(
        desired_locations=["Raleigh, NC"],
        employment_types=[SearchEmploymentType.INTERNSHIP],
    )

    result = JobSearchQueryGenerator().generate(profile, preferences)

    assert "Cybersecurity Intern Raleigh NC" in {query.query_text for query in result.queries}
    assert all(query.location == "Raleigh, NC" for query in result.queries)
    assert all("Raleigh NC" in query.query_text for query in result.queries)


def test_cybersecurity_profile_with_remote_enabled() -> None:
    """Remote-allowed preferences should produce both location and remote searches."""

    profile = _profile(primary_domain=CandidateDomain.CYBERSECURITY)
    preferences = JobSearchPreferences(
        desired_locations=["Raleigh, NC"],
        remote_preference=RemotePreference.REMOTE_ALLOWED,
        employment_types=[SearchEmploymentType.INTERNSHIP],
    )

    result = JobSearchQueryGenerator().generate(profile, preferences)

    assert any(
        query.remote and query.query_text == "Cybersecurity Intern Remote"
        for query in result.queries
    )
    assert any(
        not query.remote and query.query_text == "Cybersecurity Intern Raleigh NC"
        for query in result.queries
    )


def test_software_engineering_profile_generates_developer_queries() -> None:
    """Software engineering profiles should generate engineering and developer roles."""

    profile = _profile(
        primary_domain=CandidateDomain.SOFTWARE_ENGINEERING,
        core_skills=["Python", "FastAPI"],
    )

    result = JobSearchQueryGenerator().generate(profile)
    texts = {query.query_text for query in result.queries}

    assert "Software Engineering Intern" in texts
    assert "Backend Developer Intern" in texts
    assert "Python Developer Intern" in texts


def test_networking_profile_generates_network_queries() -> None:
    """Networking profiles should generate network operations and NOC searches."""

    profile = _profile(
        primary_domain=CandidateDomain.NETWORKING,
        core_skills=["Networking", "Cisco", "Routing"],
    )

    result = JobSearchQueryGenerator().generate(profile)
    texts = {query.query_text for query in result.queries}

    assert "Network Engineering Intern" in texts
    assert "Network Operations Intern" in texts
    assert "NOC Intern" in texts


def test_mixed_cybersecurity_software_profile_uses_secondary_roles() -> None:
    """Secondary-domain roles should be generated at reduced priority."""

    profile = _profile(
        primary_domain=CandidateDomain.CYBERSECURITY,
        secondary_domains=[CandidateDomain.SOFTWARE_ENGINEERING],
        core_skills=["Python", "Linux"],
    )

    result = JobSearchQueryGenerator().generate(profile)
    software_query = next(
        query for query in result.queries if query.query_text == "Software Engineering Intern"
    )

    assert software_query.priority == QueryPriority.MEDIUM


def test_preferences_exclude_roles_and_companies() -> None:
    """Excluded roles should be removed and excluded companies should become filter terms."""

    profile = _profile(primary_domain=CandidateDomain.CYBERSECURITY)
    preferences = JobSearchPreferences(
        excluded_roles=["SOC Analyst Intern"],
        excluded_companies=["Example Corp"],
        employment_types=[SearchEmploymentType.INTERNSHIP],
    )

    result = JobSearchQueryGenerator().generate(profile, preferences)

    assert all(query.role != "SOC Analyst Intern" for query in result.queries)
    assert "company:Example Corp" in result.excluded_terms


def test_duplicate_query_prevention_normalizes_case_whitespace_and_locations() -> None:
    """Equivalent roles and locations should not create duplicate queries."""

    profile = _profile(
        primary_domain=CandidateDomain.CYBERSECURITY,
        target_roles=["Cybersecurity Intern", " cyberSECURITY   intern "],
    )
    preferences = JobSearchPreferences(
        desired_locations=["Raleigh, NC", "raleigh nc", " Raleigh,  NC "],
        employment_types=[SearchEmploymentType.INTERNSHIP],
    )

    result = JobSearchQueryGenerator().generate(profile, preferences)
    normalized = _normalized_queries([query.query_text for query in result.queries])

    assert len(normalized) == len(set(normalized))
    assert normalized.count("cybersecurity intern raleigh nc") == 1


def test_missing_location_generates_role_only_queries() -> None:
    """No location preference should never result in an invented location."""

    profile = _profile(primary_domain=CandidateDomain.IT_SUPPORT)
    preferences = JobSearchPreferences(employment_types=[SearchEmploymentType.INTERNSHIP])

    result = JobSearchQueryGenerator().generate(profile, preferences)

    assert all(query.location is None for query in result.queries)
    assert all(not query.remote and not query.hybrid for query in result.queries)
    assert "IT Intern" in {query.query_text for query in result.queries}


def test_default_employment_types_include_entry_level_fallback() -> None:
    """Missing employment preferences should generate internship and entry-level queries."""

    profile = _profile(primary_domain=CandidateDomain.SOFTWARE_ENGINEERING)

    result = JobSearchQueryGenerator().generate(profile)
    employment_types = {query.employment_type for query in result.queries}

    assert SearchEmploymentType.INTERNSHIP in employment_types
    assert SearchEmploymentType.ENTRY_LEVEL in employment_types
    assert any(query.query_text.startswith("Entry Level ") for query in result.queries)


def test_desired_roles_receive_high_priority() -> None:
    """Explicit desired roles should influence generation without replacing the profile."""

    profile = _profile(primary_domain=CandidateDomain.SOFTWARE_ENGINEERING)
    preferences = JobSearchPreferences(
        desired_roles=["Quality Assurance Intern"],
        employment_types=[SearchEmploymentType.INTERNSHIP],
    )

    result = JobSearchQueryGenerator().generate(profile, preferences)
    desired = next(query for query in result.queries if query.role == "Quality Assurance Intern")

    assert desired.priority == QueryPriority.HIGH
    assert any(query.role == "Software Engineering Intern" for query in result.queries)
