"""Tests for deterministic candidate/job fit scoring and ranking."""

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    CandidateProfile,
    EmploymentType,
    ExperienceLevel,
    JobPosting,
    JobSearchPreferences,
    JobSourceType,
    ProfileValidationStatus,
    RecommendationLevel,
    RemotePreference,
    WorkArrangement,
)
from ai_internship_assistant.services.job_ranking import JobFitScoringService


def _cybersecurity_profile(
    *,
    skills: list[str] | None = None,
    certifications: list[str] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        candidate_name="Example Candidate",
        experience_level=ExperienceLevel.STUDENT,
        primary_domain=CandidateDomain.CYBERSECURITY,
        secondary_domains=[CandidateDomain.SOFTWARE_ENGINEERING, CandidateDomain.NETWORKING],
        core_skills=skills if skills is not None else ["Python", "Linux", "Networking"],
        supporting_skills=["Git"],
        certifications=certifications if certifications is not None else ["Security+"],
        technologies=skills if skills is not None else ["Python", "Linux", "Networking"],
        target_roles=["Cybersecurity Intern", "SOC Analyst Intern"],
        industry_keywords=["Cybersecurity", "Networking"],
        search_keywords=[],
        education_level="Bachelor's",
        confidence_score=0.9,
        profile_summary="Cybersecurity student.",
        validation_status=ProfileValidationStatus.CLEAN,
        validation_messages=[],
    )


def _job(
    *,
    identifier: str,
    title: str,
    description: str | None = None,
    technologies: list[str] | None = None,
    certifications: list[str] | None = None,
    employment_type: EmploymentType = EmploymentType.INTERNSHIP,
    location: str | None = "Raleigh, NC",
    work_arrangement: WorkArrangement = WorkArrangement.ONSITE,
) -> JobPosting:
    return JobPosting(
        id=identifier,
        source=JobSourceType.MOCK,
        source_name="Mock",
        title=title,
        company=f"Company {identifier}",
        location=location,
        employment_type=employment_type,
        work_arrangement=work_arrangement,
        description=description,
        technologies=technologies or [],
        certifications=certifications or [],
    )


def test_perfect_cybersecurity_internship_match() -> None:
    """A direct cybersecurity internship with matching evidence should rank highly."""

    job = _job(
        identifier="perfect",
        title="Cybersecurity Intern",
        description=(
            "Cybersecurity internship supporting Python, Linux, networking, "
            "Security+, network security, and threat detection."
        ),
        technologies=["Python", "Linux", "Networking"],
        certifications=["Security+"],
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert score.overall_score >= 85
    assert set(score.matched_skills) >= {"Python", "Linux", "Networking"}
    assert score.matched_certifications == ["Security+"]
    assert score.disqualifying_flags == []
    assert "internship-level" in score.explanation


def test_good_soc_analyst_internship_match() -> None:
    """A SOC internship should score well for an aligned cybersecurity profile."""

    job = _job(
        identifier="soc",
        title="SOC Analyst Intern",
        description="Support SOC alert triage, incident response, SIEM, Linux, and log analysis.",
        technologies=["Linux", "SIEM"],
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert score.overall_score >= 70
    assert "Linux" in score.matched_skills
    assert "siem" in [skill.casefold() for skill in score.missing_skills]


def test_software_internship_is_possible_for_cybersecurity_candidate() -> None:
    """A software internship should rank below aligned security internships."""

    service = JobFitScoringService()
    profile = _cybersecurity_profile()
    security = _job(
        identifier="security",
        title="SOC Analyst Intern",
        description="SOC security operations with Linux and networking.",
        technologies=["Linux", "Networking"],
    )
    software = _job(
        identifier="software",
        title="Software Engineering Intern",
        description="Build Python APIs and use Git.",
        technologies=["Python", "Git"],
    )

    ranked = service.rank_jobs(profile, [software, security])

    assert ranked.results[0].job is security
    assert ranked.results[1].job is software


def test_senior_security_architect_scores_poorly() -> None:
    """Senior roles should receive explicit flags and strong penalties."""

    job = _job(
        identifier="senior",
        title="Senior Security Architect",
        description="Requires 10+ years and leads enterprise security architecture.",
        employment_type=EmploymentType.FULL_TIME,
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert score.overall_score < 40
    assert "senior_level_role" in score.disqualifying_flags
    assert "requires_5_plus_years" in score.disqualifying_flags


def test_missing_siem_reduces_but_does_not_destroy_score() -> None:
    """Missing aspirational internship skills should be visible without zeroing fit."""

    with_siem = _job(
        identifier="with-siem",
        title="SOC Analyst Intern",
        description="Internship using Python, Linux, networking, and SIEM.",
        technologies=["Python", "Linux", "Networking", "SIEM"],
    )
    without_siem_profile = _cybersecurity_profile()

    score = JobFitScoringService().score_job(without_siem_profile, with_siem)

    assert "siem" in [skill.casefold() for skill in score.missing_skills]
    assert score.overall_score >= 60


def test_security_plus_match_boosts_certification_component() -> None:
    """Explicit certification alignment should boost certification scoring."""

    service = JobFitScoringService()
    job = _job(
        identifier="cert",
        title="Cybersecurity Intern",
        description="Security+ preferred for this cybersecurity internship.",
        certifications=["Security+"],
    )

    with_cert = service.score_job(_cybersecurity_profile(), job)
    without_cert = service.score_job(_cybersecurity_profile(certifications=[]), job)

    assert with_cert.certification_match_score > without_cert.certification_match_score
    assert with_cert.overall_score > without_cert.overall_score


def test_remote_match_boosts_location_score_when_preferred() -> None:
    """Remote preference should reward remote jobs."""

    job = _job(
        identifier="remote",
        title="Cybersecurity Intern",
        description="Remote cybersecurity internship.",
        location="Remote - United States",
        work_arrangement=WorkArrangement.REMOTE,
    )
    preferences = JobSearchPreferences(remote_preference=RemotePreference.REMOTE_ONLY)

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job, preferences)

    assert score.location_score == 100
    assert "location_mismatch" not in score.disqualifying_flags


def test_unknown_location_does_not_heavily_penalize() -> None:
    """Unknown locations should remain neutral rather than becoming disqualifying."""

    job = _job(
        identifier="unknown-location",
        title="Cybersecurity Intern",
        description="Cybersecurity internship.",
        location=None,
        work_arrangement=WorkArrangement.UNKNOWN,
    )
    preferences = JobSearchPreferences(desired_locations=["Raleigh, NC"])

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job, preferences)

    assert score.location_score == 55
    assert "location_mismatch" not in score.disqualifying_flags


def test_entry_level_role_scores_moderately_well() -> None:
    """Entry-level security roles should remain viable for an early-career candidate."""

    job = _job(
        identifier="entry",
        title="Entry Level Security Analyst",
        description="Early career security analyst role using Linux and networking.",
        employment_type=EmploymentType.FULL_TIME,
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert score.experience_level_score == 100
    assert score.overall_score >= 50


def test_internship_role_scores_higher_than_non_internship_equivalent() -> None:
    """Internship evidence should improve experience and employment components."""

    service = JobFitScoringService()
    internship = _job(
        identifier="internship",
        title="Cybersecurity Intern",
        description="Cybersecurity internship using Linux.",
    )
    full_time = _job(
        identifier="fulltime",
        title="Cybersecurity Analyst",
        description="Cybersecurity role using Linux.",
        employment_type=EmploymentType.FULL_TIME,
    )

    intern_score = service.score_job(_cybersecurity_profile(), internship)
    full_time_score = service.score_job(_cybersecurity_profile(), full_time)

    assert intern_score.overall_score > full_time_score.overall_score


def test_requires_years_and_clearance_create_flags() -> None:
    """Clearance and years requirements should be visible and reduce fit."""

    job = _job(
        identifier="flags",
        title="Security Analyst",
        description="Requires active Secret clearance and 5+ years of incident response.",
        employment_type=EmploymentType.FULL_TIME,
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert "requires_clearance" in score.disqualifying_flags
    assert "requires_5_plus_years" in score.disqualifying_flags


def test_duplicate_jobs_rank_deterministically() -> None:
    """Equivalent jobs should retain deterministic input-order-independent tie breaking."""

    first = _job(identifier="b", title="Cybersecurity Intern", description="Security internship.")
    second = _job(identifier="a", title="Cybersecurity Intern", description="Security internship.")

    ranked = JobFitScoringService().rank_jobs(_cybersecurity_profile(), [first, second])

    assert [result.job.id for result in ranked.results] == ["a", "b"]


def test_empty_job_description_is_scored_with_warning() -> None:
    """Jobs with empty descriptions should still receive a score."""

    job = _job(identifier="empty", title="Cybersecurity Intern", description=None)

    score = JobFitScoringService().score_job(_cybersecurity_profile(), job)

    assert score.overall_score >= 0
    assert "job description is empty" in score.warnings


def test_empty_candidate_skills_degrades_gracefully() -> None:
    """Empty candidate skill lists should not crash scoring."""

    job = _job(
        identifier="skills",
        title="Cybersecurity Intern",
        description="Python, Linux, networking, and SIEM internship.",
        technologies=["Python", "Linux", "Networking", "SIEM"],
    )

    score = JobFitScoringService().score_job(_cybersecurity_profile(skills=[]), job)

    assert score.skill_match_score == 0
    assert score.missing_skills


def test_multiple_jobs_rank_correctly_and_assign_recommendations() -> None:
    """Aligned, adjacent, and senior jobs should sort in expected order."""

    jobs = [
        _job(
            identifier="senior",
            title="Senior Security Architect",
            description="Requires 10+ years.",
            employment_type=EmploymentType.FULL_TIME,
        ),
        _job(
            identifier="software",
            title="Software Engineering Intern",
            description="Build Python APIs.",
            technologies=["Python"],
        ),
        _job(
            identifier="soc",
            title="SOC Analyst Intern",
            description="SOC security operations with Linux and networking.",
            technologies=["Linux", "Networking"],
        ),
    ]

    ranked = JobFitScoringService().rank_jobs(_cybersecurity_profile(), jobs)

    assert [result.job.id for result in ranked.results] == ["soc", "software", "senior"]
    assert [result.rank for result in ranked.results] == [1, 2, 3]
    assert ranked.results[-1].recommendation_level == RecommendationLevel.NOT_RECOMMENDED
    assert ranked.total_jobs == 3


def test_recommendation_levels_use_configured_thresholds() -> None:
    """Recommendation bands should map consistently from numeric scores."""

    service = JobFitScoringService()

    assert service.recommendation_level(90) == RecommendationLevel.STRONG_MATCH
    assert service.recommendation_level(75) == RecommendationLevel.GOOD_MATCH
    assert service.recommendation_level(60) == RecommendationLevel.POSSIBLE_MATCH
    assert service.recommendation_level(40) == RecommendationLevel.WEAK_MATCH
    assert service.recommendation_level(39.9) == RecommendationLevel.NOT_RECOMMENDED

