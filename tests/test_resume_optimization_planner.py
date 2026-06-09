"""Tests for deterministic pre-rewrite resume optimization planning."""

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    CandidateDomain,
    CandidateProfile,
    Education,
    Experience,
    ExperienceLevel,
    JobAnalysis,
    JobSeniority,
    KeywordInclusionStatus,
    OptimizationPriority,
    PlanPriority,
    ProfileValidationStatus,
    Project,
    RequirementLevel,
    Resume,
    ResumeOptimizationPlan,
    RoleCategory,
    Skill,
    SkillRequirement,
)
from ai_internship_assistant.services import (
    ATSMatchScoringService,
    ResumeOptimizationPlanner,
    SkillGapAnalyzer,
)


def _resume(
    *,
    skills: list[str] | None = None,
    projects: list[Project] | None = None,
    experience: list[Experience] | None = None,
) -> Resume:
    return Resume(
        full_name="Alex Candidate",
        email="alex@example.com",
        education=[
            Education(
                institution="State University",
                degree="Bachelor of Science",
                program="Cybersecurity",
            )
        ],
        skills=[Skill(name=name) for name in skills or []],
        projects=projects or [],
        experience=experience or [],
    )


def _profile(skills: list[str] | None = None) -> CandidateProfile:
    values = skills or []
    return CandidateProfile(
        candidate_name="Alex Candidate",
        experience_level=ExperienceLevel.STUDENT,
        primary_domain=CandidateDomain.CYBERSECURITY,
        core_skills=values,
        technologies=values,
        target_roles=["SOC Analyst Intern", "Cybersecurity Intern"],
        confidence_score=0.9,
        profile_summary="Cybersecurity student.",
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
    concerns: list[str] | None = None,
    role: RoleCategory = RoleCategory.CYBERSECURITY,
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
        ats_keywords=keywords or [],
        disqualifying_requirements=concerns or [],
        role_category=role,
        domain_category=role,
        seniority=JobSeniority.INTERNSHIP,
        confidence_score=0.9,
        raw_text_hash="hash",
        analysis_source=AnalysisSource.RULE_BASED,
    )


def _plan(
    resume: Resume,
    profile: CandidateProfile,
    job: JobAnalysis,
    *,
    priority: OptimizationPriority | None = None,
    score: float | None = None,
) -> ResumeOptimizationPlan:
    gap = SkillGapAnalyzer().analyze(profile, job)
    ats = ATSMatchScoringService().score(resume, profile, job, gap)
    updates: dict[str, object] = {}
    if priority is not None:
        updates["optimization_priority"] = priority
    if score is not None:
        updates["overall_score"] = score
    if updates:
        ats = ats.model_copy(update=updates)
    return ResumeOptimizationPlanner().create_plan(resume, profile, job, gap, ats)


def _packet_project(description: str = "Captured packets with Wireshark.") -> Project:
    return Project(
        name="Packet Sniffer Project",
        description=description,
        technologies=["Python", "Wireshark", "Networking"],
    )


def test_cybersecurity_internship_has_strong_safe_keywords() -> None:
    skills = ["Python", "Linux", "Networking", "Security+"]
    plan = _plan(
        _resume(skills=skills, projects=[_packet_project()]),
        _profile(skills),
        _job(required=["Python", "Linux"], preferred=["Security+"], keywords=skills),
    )

    assert {"Python", "Linux", "Security+"} <= set(plan.safe_keywords)
    assert plan.optimization_priority in {PlanPriority.HIGH, PlanPriority.MEDIUM}


def test_soc_role_with_missing_siem_and_splunk_forbids_claims() -> None:
    skills = ["Python", "Linux", "Networking"]
    plan = _plan(
        _resume(skills=skills, projects=[_packet_project()]),
        _profile(skills),
        _job(
            required=["Python", "Linux", "SIEM"],
            keywords=["Python", "Linux", "SIEM", "Splunk"],
        ),
    )

    assert {"SIEM", "Splunk"} <= set(plan.unsafe_keywords)
    assert "Used Splunk" in plan.forbidden_claims
    assert "Used SIEM" in plan.forbidden_claims


def test_software_internship_prioritizes_java_python_project() -> None:
    project = Project(
        name="API Project",
        description="Built a Java and Python API.",
        technologies=["Java", "Python"],
    )
    plan = _plan(
        _resume(skills=["Java", "Python"], projects=[project]),
        _profile(["Java", "Python"]),
        _job(
            title="Software Engineering Intern",
            required=["Java", "Python"],
            keywords=["Java", "Python", "API"],
            role=RoleCategory.SOFTWARE_ENGINEERING,
        ),
    )

    assert plan.project_emphasis_plan[0].project_name == "API Project"
    assert plan.project_emphasis_plan[0].relevance_score > 50


def test_job_with_mostly_unsafe_keywords_limits_improvement() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(required=["Splunk", "SIEM", "AWS"], keywords=["Splunk", "SIEM", "AWS"]),
    )

    assert len(plan.unsafe_keywords) >= 3
    assert plan.expected_score_improvement.high <= 6


def test_resume_without_projects_returns_warning() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(required=["Python"], keywords=["Python"]),
    )

    assert plan.project_emphasis_plan == []
    assert "resume contains no projects to emphasize" in plan.warnings


def test_resume_without_experience_returns_warning() -> None:
    plan = _plan(
        _resume(skills=["Python"], projects=[_packet_project()]),
        _profile(["Python"]),
        _job(required=["Python"], keywords=["Python"]),
    )

    assert plan.experience_emphasis_plan == []
    assert "resume contains no experience entries to emphasize" in plan.warnings


def test_nontechnical_experience_is_not_recast_as_cybersecurity() -> None:
    experience = Experience(
        organization="Restaurant",
        title="Team Member",
        bullets=["Collaborated with team members and assisted customers."],
    )
    job = _job(keywords=["SIEM"], required=["SIEM"])
    job = job.model_copy(update={"soft_skills": ["collaboration", "communication"]})
    plan = _plan(_resume(experience=[experience]), _profile(), job)

    experience_plan = plan.experience_emphasis_plan[0]
    assert "do not recast" not in experience_plan.recommended_strategy
    assert "SIEM" not in experience_plan.related_job_keywords
    assert "Used SIEM" in experience_plan.forbidden_claims


def test_skill_reordering_promotes_matched_required_skills() -> None:
    plan = _plan(
        _resume(skills=["Excel", "Python", "Linux"]),
        _profile(["Excel", "Python", "Linux"]),
        _job(required=["Python", "Linux"], keywords=["Python", "Linux"]),
    )

    assert plan.skill_reordering_plan.recommended_order[:2] == ["Python", "Linux"]
    assert "Python" in plan.skill_reordering_plan.promoted_skills


def test_missing_unsafe_skill_is_learning_only() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(required=["Splunk"], keywords=["Splunk"]),
    )

    keyword = next(item for item in plan.keyword_inclusion_plan if item.keyword == "Splunk")
    assert keyword.inclusion_status == KeywordInclusionStatus.LEARNING_RECOMMENDATION_ONLY
    assert keyword.risk_level.value == "high"


def test_related_skill_is_related_only_not_safe_to_include() -> None:
    plan = _plan(
        _resume(skills=["Networking"]),
        _profile(["Networking"]),
        _job(required=["DNS"], keywords=["DNS"]),
    )

    keyword = next(item for item in plan.keyword_inclusion_plan if item.keyword == "DNS")
    assert keyword.inclusion_status == KeywordInclusionStatus.RELATED_ONLY
    assert "DNS" not in plan.safe_keywords


def test_exact_related_phrase_in_project_is_safe_to_emphasize() -> None:
    project = _packet_project("Captured and analyzed network traffic using Wireshark.")
    plan = _plan(
        _resume(skills=["Networking"], projects=[project]),
        _profile(["Networking"]),
        _job(required=["network traffic analysis"], keywords=["network traffic analysis"]),
    )

    keyword = next(
        item for item in plan.keyword_inclusion_plan if item.keyword == "network traffic analysis"
    )
    assert keyword.inclusion_status == KeywordInclusionStatus.SAFE_TO_EMPHASIZE


def test_high_baseline_produces_small_improvement_estimate() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(required=["Python"], keywords=["Python"]),
        score=95,
    )

    assert plan.expected_score_improvement.high <= 4


def test_low_baseline_with_safe_opportunities_can_be_high_priority() -> None:
    skills = ["Python", "Linux", "Networking", "Security+"]
    plan = _plan(
        _resume(skills=skills),
        _profile(skills),
        _job(required=["Python", "Linux"], keywords=skills),
        priority=OptimizationPriority.HIGH,
        score=60,
    )

    assert plan.optimization_priority == PlanPriority.HIGH


def test_disqualifying_concern_produces_skip() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(concerns=["requires 5+ years of experience"]),
    )

    assert plan.optimization_priority == PlanPriority.SKIP
    assert any("Verify eligibility" in risk.mitigation for risk in plan.risks)


def test_forbidden_claims_are_generated_for_unsafe_keywords() -> None:
    plan = _plan(
        _resume(skills=["Python"]),
        _profile(["Python"]),
        _job(required=["AWS"], keywords=["AWS"]),
    )

    assert "Used AWS" in plan.forbidden_claims
    assert "Built production solutions with AWS" in plan.forbidden_claims


def test_plan_does_not_mutate_inputs() -> None:
    resume = _resume(skills=["Python"], projects=[_packet_project()])
    profile = _profile(["Python"])
    job = _job(required=["Python", "SIEM"], keywords=["Python", "SIEM"])
    gap = SkillGapAnalyzer().analyze(profile, job)
    ats = ATSMatchScoringService().score(resume, profile, job, gap)
    before = [
        resume.model_dump(),
        profile.model_dump(),
        job.model_dump(),
        gap.model_dump(),
        ats.model_dump(),
    ]

    ResumeOptimizationPlanner().create_plan(resume, profile, job, gap, ats)

    assert before == [
        resume.model_dump(),
        profile.model_dump(),
        job.model_dump(),
        gap.model_dump(),
        ats.model_dump(),
    ]
