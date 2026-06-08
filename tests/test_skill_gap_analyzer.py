"""Tests for deterministic, factual candidate/job skill-gap analysis."""

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    CandidateDomain,
    CandidateProfile,
    ConcernSeverity,
    ExperienceLevel,
    GapSeverity,
    JobAnalysis,
    JobSeniority,
    MatchType,
    ProfileValidationStatus,
    RequirementLevel,
    RoleCategory,
    SkillRequirement,
)
from ai_internship_assistant.services import SkillGapAnalyzer


def _profile(
    *,
    skills: list[str] | None = None,
    certifications: list[str] | None = None,
    experience_level: ExperienceLevel = ExperienceLevel.STUDENT,
) -> CandidateProfile:
    return CandidateProfile(
        candidate_name="Alex Candidate",
        experience_level=experience_level,
        primary_domain=CandidateDomain.CYBERSECURITY,
        core_skills=skills or [],
        certifications=certifications or [],
        technologies=skills or [],
        target_roles=["Cybersecurity Intern"],
        confidence_score=0.9,
        profile_summary="Cybersecurity candidate.",
        validation_status=ProfileValidationStatus.CLEAN,
    )


def _requirement(
    name: str,
    level: RequirementLevel,
    evidence: str | None = None,
) -> SkillRequirement:
    return SkillRequirement(
        name=name,
        category="technical_skill",
        requirement_level=level,
        evidence=evidence or name,
        confidence=0.95,
    )


def _job(
    *,
    required: list[str] | None = None,
    preferred: list[str] | None = None,
    certifications: list[str] | None = None,
    ats_keywords: list[str] | None = None,
    cybersecurity_terms: list[str] | None = None,
    concerns: list[str] | None = None,
    seniority: JobSeniority = JobSeniority.INTERNSHIP,
) -> JobAnalysis:
    return JobAnalysis(
        job_id="job-1",
        job_title="SOC Analyst Intern",
        company="Example Security",
        normalized_title="soc analyst intern",
        required_skills=[
            _requirement(name, RequirementLevel.REQUIRED, f"{name} required")
            for name in required or []
        ],
        preferred_skills=[
            _requirement(name, RequirementLevel.PREFERRED, f"{name} preferred")
            for name in preferred or []
        ],
        certifications=certifications or [],
        ats_keywords=ats_keywords or [],
        cybersecurity_terms=cybersecurity_terms or [],
        disqualifying_requirements=concerns or [],
        role_category=RoleCategory.CYBERSECURITY,
        domain_category=RoleCategory.CYBERSECURITY,
        seniority=seniority,
        confidence_score=0.9,
        raw_text_hash="abc123",
        analysis_source=AnalysisSource.RULE_BASED,
    )


def test_exact_skill_match() -> None:
    report = SkillGapAnalyzer().analyze(_profile(skills=["Python"]), _job(required=["Python"]))

    assert report.matched_required_skills[0].match_type == MatchType.EXACT
    assert report.matched_required_skills[0].candidate_evidence == "Python"
    assert report.missing_required_skills == []


def test_normalized_skill_match() -> None:
    report = SkillGapAnalyzer().analyze(_profile(skills=["Python3"]), _job(required=["Python"]))

    assert report.matched_required_skills[0].match_type == MatchType.NORMALIZED
    assert report.matched_required_skills[0].candidate_evidence == "Python3"


def test_alias_certification_match() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(certifications=["Security+"]),
        _job(preferred=["CompTIA Security+"], certifications=["CompTIA Security+"]),
    )

    assert report.matched_certifications[0].candidate_evidence == "Security+"
    assert report.matched_certifications[0].match_type == MatchType.NORMALIZED
    assert report.missing_certifications == []


def test_missing_required_skill_is_not_safe_to_add() -> None:
    report = SkillGapAnalyzer().analyze(_profile(skills=["Python"]), _job(required=["Splunk"]))

    gap = report.missing_required_skills[0]
    assert gap.skill_name == "Splunk"
    assert gap.safe_to_add_to_resume is False
    assert gap.gap_severity == GapSeverity.MEDIUM
    assert "beginner Splunk lab" in gap.recommendation


def test_missing_preferred_skill_is_low_severity() -> None:
    report = SkillGapAnalyzer().analyze(_profile(), _job(preferred=["Docker"]))

    assert report.missing_preferred_skills[0].gap_severity == GapSeverity.LOW
    assert report.overall_gap_severity == GapSeverity.LOW


def test_related_networking_skill_creates_opportunity_not_direct_match() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Networking"]),
        _job(required=["DNS"], ats_keywords=["DNS"]),
    )

    assert report.matched_required_skills == []
    assert report.missing_required_skills[0].skill_name == "DNS"
    assert report.missing_required_skills[0].gap_severity == GapSeverity.LOW
    assert report.resume_emphasis_opportunities[0].existing_candidate_skill == "Networking"
    assert report.resume_emphasis_opportunities[0].related_job_keyword == "DNS"


def test_related_packet_analysis_opportunity_is_safe_and_explicit() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Packet Sniffer"]),
        _job(required=["network traffic analysis"], ats_keywords=["network traffic analysis"]),
    )

    opportunity = report.resume_emphasis_opportunities[0]
    assert opportunity.existing_candidate_skill == "Packet Sniffer"
    assert "not equivalent" in opportunity.explanation
    assert "do not claim direct network traffic analysis experience" in (
        opportunity.safe_resume_strategy
    )
    assert report.missing_required_skills[0].safe_to_add_to_resume is False


def test_security_plus_matches_comptia_security_plus_skill() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Security+"]),
        _job(required=["CompTIA Security+"]),
    )

    assert report.matched_required_skills[0].match_type == MatchType.NORMALIZED


def test_preferred_cissp_is_not_critical_for_internship() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(),
        _job(preferred=["CISSP"], certifications=["CISSP"]),
    )

    assert report.missing_certifications[0].gap_severity == GapSeverity.LOW
    assert report.overall_gap_severity == GapSeverity.LOW
    assert "do not add it to the resume unless earned" in (
        report.missing_certifications[0].recommendation
    )


def test_five_plus_years_requirement_creates_disqualifying_concern() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(),
        _job(concerns=["requires 5+ years of experience"]),
    )

    concern = report.disqualifying_concerns[0]
    assert concern.concern_type == "experience_requirement"
    assert concern.severity == ConcernSeverity.DISQUALIFYING
    assert report.overall_gap_severity == GapSeverity.CRITICAL


def test_clearance_requirement_creates_high_concern() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(),
        _job(concerns=["requires security clearance"]),
    )

    concern = report.disqualifying_concerns[0]
    assert concern.concern_type == "security_clearance"
    assert concern.severity == ConcernSeverity.HIGH
    assert "Verify eligibility" in concern.description


def test_no_candidate_skills_degrades_gracefully() -> None:
    report = SkillGapAnalyzer().analyze(_profile(), _job(required=["Python", "Linux"]))

    assert len(report.missing_required_skills) == 2
    assert "candidate profile contains no skills or technologies" in report.warnings


def test_no_job_skills_degrades_gracefully() -> None:
    report = SkillGapAnalyzer().analyze(_profile(skills=["Python"]), _job())

    assert report.matched_required_skills == []
    assert report.missing_required_skills == []
    assert report.overall_gap_severity == GapSeverity.LOW
    assert "job analysis contains no required or preferred skills" in report.warnings


def test_multiple_matched_and_missing_skills_are_separated() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Python", "Linux"]),
        _job(required=["Python", "Linux", "SIEM"], preferred=["Splunk", "Docker"]),
    )

    assert {match.skill_name for match in report.matched_required_skills} == {"Python", "Linux"}
    assert [gap.skill_name for gap in report.missing_required_skills] == ["SIEM"]
    assert {gap.skill_name for gap in report.missing_preferred_skills} == {"Splunk", "Docker"}
    assert "Missing skills include SIEM, Splunk, Docker." in report.match_summary


def test_overall_severity_low_when_all_required_skills_match() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Python", "Linux"]),
        _job(required=["Python", "Linux"]),
    )

    assert report.overall_gap_severity == GapSeverity.LOW


def test_overall_severity_high_for_multiple_required_gaps() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Python"]),
        _job(
            required=["Linux", "SIEM", "Splunk"],
            seniority=JobSeniority.ENTRY_LEVEL,
        ),
    )

    assert report.overall_gap_severity == GapSeverity.HIGH


def test_resume_emphasis_opportunity_never_turns_into_direct_claim() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(skills=["Wireshark"]),
        _job(required=["packet analysis"], ats_keywords=["packet analysis"]),
    )

    assert report.matched_required_skills == []
    assert report.missing_required_skills[0].safe_to_add_to_resume is False
    assert "do not claim direct packet analysis experience" in (
        report.resume_emphasis_opportunities[0].safe_resume_strategy
    )


def test_learning_recommendations_are_deduplicated() -> None:
    report = SkillGapAnalyzer().analyze(
        _profile(),
        _job(required=["Splunk"], preferred=["Splunk"]),
    )

    assert len(report.learning_recommendations) == 1


def test_inputs_are_not_mutated() -> None:
    profile = _profile(skills=["Python"])
    job = _job(required=["Python", "SIEM"])
    profile_before = profile.model_dump()
    job_before = job.model_dump()

    SkillGapAnalyzer().analyze(profile, job)

    assert profile.model_dump() == profile_before
    assert job.model_dump() == job_before
