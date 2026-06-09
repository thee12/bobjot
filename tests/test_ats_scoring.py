"""Tests for deterministic estimated ATS resume/job match scoring."""

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    ATSMatchReport,
    ATSRecommendationLevel,
    CandidateDomain,
    CandidateProfile,
    Certification,
    Education,
    Experience,
    ExperienceLevel,
    JobAnalysis,
    JobSeniority,
    OptimizationPriority,
    ProfileValidationStatus,
    Project,
    RequirementLevel,
    Resume,
    RoleCategory,
    Skill,
    SkillRequirement,
)
from ai_internship_assistant.services import ATSMatchScoringService, SkillGapAnalyzer


def _resume(
    *,
    skills: list[str] | None = None,
    certifications: list[str] | None = None,
    program: str = "Cybersecurity",
    degree: str = "Bachelor of Science",
    include_projects: bool = True,
    include_experience: bool = True,
) -> Resume:
    skill_values = skills or []
    return Resume(
        full_name="Alex Candidate",
        email="alex@example.com",
        summary="Cybersecurity student seeking a SOC Analyst internship.",
        education=[Education(institution="State University", degree=degree, program=program)],
        experience=(
            [
                Experience(
                    organization="Campus IT",
                    title="IT Support Intern",
                    bullets=["Investigated Linux and network issues."],
                    technologies=["Linux", "Networking"],
                )
            ]
            if include_experience
            else []
        ),
        projects=(
            [
                Project(
                    name="Packet Analysis Lab",
                    description="Analyzed network traffic with Python.",
                    technologies=["Python", "Wireshark", "Networking"],
                )
            ]
            if include_projects
            else []
        ),
        certifications=[Certification(name=name) for name in certifications or []],
        skills=[Skill(name=name) for name in skill_values],
    )


def _profile(
    *,
    skills: list[str] | None = None,
    certifications: list[str] | None = None,
    target_roles: list[str] | None = None,
    primary_domain: CandidateDomain = CandidateDomain.CYBERSECURITY,
    secondary_domains: list[CandidateDomain] | None = None,
    experience_level: ExperienceLevel = ExperienceLevel.STUDENT,
    education_level: str | None = "Bachelor's",
) -> CandidateProfile:
    values = skills or []
    return CandidateProfile(
        candidate_name="Alex Candidate",
        experience_level=experience_level,
        primary_domain=primary_domain,
        secondary_domains=secondary_domains or [],
        core_skills=values,
        certifications=certifications or [],
        technologies=values,
        target_roles=target_roles or ["SOC Analyst Intern", "Cybersecurity Intern"],
        industry_keywords=[primary_domain.value],
        education_level=education_level,
        confidence_score=0.9,
        profile_summary="Candidate profile.",
        validation_status=ProfileValidationStatus.CLEAN,
    )


def _requirement(name: str, level: RequirementLevel) -> SkillRequirement:
    return SkillRequirement(
        name=name,
        category="technical_skill",
        requirement_level=level,
        evidence=f"{name} {level.value}",
        confidence=0.95,
    )


def _job(
    *,
    title: str = "SOC Analyst Intern",
    required: list[str] | None = None,
    preferred: list[str] | None = None,
    keywords: list[str] | None = None,
    certifications: list[str] | None = None,
    education: list[str] | None = None,
    concerns: list[str] | None = None,
    role: RoleCategory = RoleCategory.CYBERSECURITY,
    seniority: JobSeniority = JobSeniority.INTERNSHIP,
    confidence: float = 0.9,
) -> JobAnalysis:
    return JobAnalysis(
        job_id="job-1",
        job_title=title,
        company="Example Company",
        normalized_title=title.casefold(),
        required_skills=[
            _requirement(name, RequirementLevel.REQUIRED) for name in required or []
        ],
        preferred_skills=[
            _requirement(name, RequirementLevel.PREFERRED) for name in preferred or []
        ],
        technical_tools=[term for term in keywords or [] if term in {"Splunk", "Wireshark"}],
        certifications=certifications or [],
        ats_keywords=keywords or [],
        education_requirements=education or [],
        disqualifying_requirements=concerns or [],
        role_category=role,
        domain_category=role,
        seniority=seniority,
        confidence_score=confidence,
        raw_text_hash="hash",
        analysis_source=AnalysisSource.RULE_BASED,
    )


def _score(
    resume: Resume,
    profile: CandidateProfile,
    job: JobAnalysis,
) -> ATSMatchReport:
    gap = SkillGapAnalyzer().analyze(profile, job)
    return ATSMatchScoringService().score(resume, profile, job, gap)


def test_excellent_soc_internship_match() -> None:
    skills = ["Python", "Linux", "Networking", "SIEM", "Security+", "Splunk"]
    resume = _resume(skills=skills, certifications=["Security+"])
    profile = _profile(skills=skills, certifications=["Security+"])
    job = _job(
        required=["Python", "Linux", "Networking", "SIEM"],
        preferred=["Security+"],
        certifications=["CompTIA Security+"],
        keywords=["SOC Analyst Intern", *skills],
        education=["currently pursuing bachelor's degree in Cybersecurity"],
    )

    report = _score(resume, profile, job)

    assert report.overall_score >= 90
    assert report.recommendation_level == ATSRecommendationLevel.EXCELLENT_MATCH
    assert report.required_skill_coverage == 100
    assert report.certification_coverage == 100


def test_good_cybersecurity_match_with_missing_siem() -> None:
    skills = ["Python", "Linux", "Networking", "Security+"]
    report = _score(
        _resume(skills=skills, certifications=["Security+"]),
        _profile(skills=skills, certifications=["Security+"]),
        _job(
            required=["Python", "Linux", "Networking", "SIEM"],
            preferred=["Security+"],
            certifications=["CompTIA Security+"],
            keywords=["SOC Analyst Intern", "Python", "Linux", "Networking", "SIEM", "Splunk"],
        ),
    )

    assert 60 <= report.overall_score < 90
    assert "SIEM" in report.missing_required_skills
    assert "Splunk" in report.missing_ats_keywords


def test_software_internship_partial_match() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"], target_roles=["Cybersecurity Intern"]),
        _job(
            title="Frontend Engineering Intern",
            required=["JavaScript", "React"],
            preferred=["TypeScript"],
            keywords=["Frontend Engineering Intern", "JavaScript", "React", "TypeScript"],
            role=RoleCategory.SOFTWARE_ENGINEERING,
        ),
    )

    assert report.role_alignment_score < 50
    assert report.required_skill_coverage == 0
    assert report.overall_score < 70


def test_senior_role_with_five_years_receives_large_penalty() -> None:
    report = _score(
        _resume(skills=["Python", "Linux"]),
        _profile(skills=["Python", "Linux"]),
        _job(
            title="Senior Security Architect",
            required=["Python", "Linux"],
            keywords=["Python", "Linux"],
            concerns=["requires 5+ years of experience"],
            seniority=JobSeniority.SENIOR,
        ),
    )

    assert report.component_scores.disqualifier_penalty >= 40
    assert report.experience_alignment_score == 10
    assert report.optimization_priority == OptimizationPriority.NOT_WORTH_OPTIMIZING


def test_missing_required_skill_reduces_score_more_than_preferred() -> None:
    resume = _resume(skills=["Python"])
    profile = _profile(skills=["Python"])
    required_gap = _score(
        resume,
        profile,
        _job(required=["Python", "Splunk"], keywords=["Python", "Splunk"]),
    )
    preferred_gap = _score(
        resume,
        profile,
        _job(required=["Python"], preferred=["Splunk"], keywords=["Python", "Splunk"]),
    )

    assert required_gap.overall_score < preferred_gap.overall_score


def test_security_plus_matches_comptia_security_plus() -> None:
    report = _score(
        _resume(skills=["Security+"], certifications=["Security+"]),
        _profile(skills=["Security+"], certifications=["Security+"]),
        _job(
            preferred=["CompTIA Security+"],
            certifications=["CompTIA Security+"],
            keywords=["CompTIA Security+"],
        ),
    )

    assert report.certification_coverage == 100
    assert "CompTIA Security+" in report.matched_ats_keywords


def test_no_ats_keywords_uses_neutral_score_and_warning() -> None:
    report = _score(_resume(skills=["Python"]), _profile(skills=["Python"]), _job())

    assert report.component_scores.keyword_score == 70
    assert report.keyword_coverage.total_keywords == 0
    assert "no ATS keywords were detected" in report.warnings


def test_no_required_skills_uses_neutral_score_and_warning() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"]),
        _job(preferred=["Python"], keywords=["Python"]),
    )

    assert report.required_skill_coverage == 70
    assert "no required skills were detected; neutral coverage was used" in report.warnings


def test_empty_candidate_skills_generates_warning_and_low_coverage() -> None:
    report = _score(
        _resume(skills=[]),
        _profile(skills=[]),
        _job(required=["Python", "Linux"], keywords=["Python", "Linux"]),
    )

    assert report.required_skill_coverage == 0
    assert "candidate profile contains no skills or technologies" in report.warnings


def test_strong_role_alignment() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"], target_roles=["SOC Analyst Intern"]),
        _job(keywords=["SOC Analyst Intern"]),
    )

    assert report.role_alignment_score == 100


def test_weak_role_alignment() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(
            skills=["Python"],
            target_roles=["Data Science Intern"],
            primary_domain=CandidateDomain.DATA_SCIENCE,
        ),
        _job(title="SOC Analyst Intern", role=RoleCategory.CYBERSECURITY),
    )

    assert report.role_alignment_score < 30


def test_education_match() -> None:
    report = _score(
        _resume(skills=["Python"], program="Cybersecurity"),
        _profile(skills=["Python"]),
        _job(education=["currently pursuing bachelor's degree in Cybersecurity"]),
    )

    assert report.education_alignment_score == 100


def test_education_mismatch() -> None:
    report = _score(
        _resume(skills=["Python"], program="Cybersecurity"),
        _profile(skills=["Python"], education_level="Bachelor's"),
        _job(education=["Master's degree required"]),
    )

    assert report.education_alignment_score == 20


def test_disqualifying_concern_penalty_is_applied() -> None:
    without = _score(_resume(skills=["Python"]), _profile(skills=["Python"]), _job())
    with_concern = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"]),
        _job(concerns=["requires security clearance"]),
    )

    assert with_concern.overall_score < without.overall_score
    assert with_concern.component_scores.disqualifier_penalty == 20


def test_optimization_priority_high_for_improvable_match() -> None:
    report = _score(
        _resume(skills=["Python", "Linux"]),
        _profile(skills=["Python", "Linux"]),
        _job(
            required=["Python", "Linux", "SIEM"],
            preferred=["Splunk"],
            keywords=["SOC Analyst Intern", "Python", "Linux", "SIEM", "Splunk"],
        ),
    )

    assert report.optimization_priority == OptimizationPriority.HIGH


def test_optimization_priority_not_worth_for_major_concern() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"]),
        _job(concerns=["requires 5+ years of experience"]),
    )

    assert report.optimization_priority == OptimizationPriority.NOT_WORTH_OPTIMIZING


def test_section_scores_are_generated() -> None:
    report = _score(
        _resume(skills=["Python", "Linux"], certifications=["Security+"]),
        _profile(skills=["Python", "Linux"], certifications=["Security+"]),
        _job(keywords=["Python", "Linux", "Security+", "Splunk"]),
    )

    assert {section.section_name for section in report.resume_section_scores} == {
        "Skills",
        "Projects",
        "Experience",
        "Certifications",
        "Education",
    }
    skills_section = next(
        section for section in report.resume_section_scores if section.section_name == "Skills"
    )
    assert skills_section.strengths


def test_high_value_missing_keywords_are_detected() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"]),
        _job(
            required=["Python", "SIEM"],
            keywords=["SOC Analyst Intern", "Python", "SIEM", "Splunk"],
        ),
    )

    assert "SIEM" in report.keyword_coverage.high_value_missing_keywords
    assert "Splunk" in report.keyword_coverage.high_value_missing_keywords


def test_missing_unsafe_keyword_is_not_recommended_for_direct_addition() -> None:
    report = _score(
        _resume(skills=["Python"]),
        _profile(skills=["Python"]),
        _job(required=["Python", "Splunk"], keywords=["Python", "Splunk"]),
    )

    assert any("Do not add Splunk" in guidance for guidance in report.optimization_guidance)
    assert not any("Add Splunk" in guidance for guidance in report.optimization_guidance)


def test_inputs_are_not_mutated() -> None:
    resume = _resume(skills=["Python"])
    profile = _profile(skills=["Python"])
    job = _job(required=["Python"], keywords=["Python"])
    gap = SkillGapAnalyzer().analyze(profile, job)
    snapshots = [resume.model_dump(), profile.model_dump(), job.model_dump(), gap.model_dump()]

    ATSMatchScoringService().score(resume, profile, job, gap)

    assert snapshots == [
        resume.model_dump(),
        profile.model_dump(),
        job.model_dump(),
        gap.model_dump(),
    ]
