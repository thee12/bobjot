"""Tests for deterministic, traceable full-resume optimization."""

from collections.abc import Callable

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    ATSMatchReport,
    BulletRewriteRequest,
    BulletRewriteResult,
    BulletRewriteSource,
    CandidateDomain,
    CandidateProfile,
    Certification,
    ChangeType,
    Education,
    Experience,
    ExperienceLevel,
    JobAnalysis,
    JobSeniority,
    ProfileValidationStatus,
    Project,
    RequirementLevel,
    Resume,
    ResumeOptimizationOptions,
    ResumeOptimizationRequest,
    RoleCategory,
    SafetyStatus,
    Skill,
    SkillGapReport,
    SkillRequirement,
)
from ai_internship_assistant.services import (
    ATSMatchScoringService,
    FullResumeOptimizer,
    ResumeOptimizationPlanner,
    SkillGapAnalyzer,
)


class MockBulletRewriter:
    """Configurable rewriter that never performs network calls."""

    def __init__(
        self,
        transform: Callable[[BulletRewriteRequest], str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.transform = transform or (lambda request: request.original_bullet)
        self.error = error
        self.requests: list[BulletRewriteRequest] = []

    def rewrite(self, request: BulletRewriteRequest) -> BulletRewriteResult:
        self.requests.append(request)
        if self.error:
            raise self.error
        rewritten = self.transform(request)
        return BulletRewriteResult(
            original_bullet=request.original_bullet,
            rewritten_bullet=rewritten,
            changed=rewritten != request.original_bullet,
            included_keywords=[
                keyword
                for keyword in request.safe_keywords
                if keyword.casefold() in rewritten.casefold()
            ],
            avoided_keywords=[
                keyword
                for keyword in request.unsafe_keywords
                if keyword.casefold() not in rewritten.casefold()
            ],
            safety_violations=[],
            confidence_score=0.9,
            explanation="Mocked evidence-preserving rewrite.",
            rewrite_source=BulletRewriteSource.OPENAI,
        )


def _requirement(name: str, level: RequirementLevel) -> SkillRequirement:
    return SkillRequirement(
        name=name,
        category="technical_skill",
        requirement_level=level,
        evidence=f"{name} is {level.value}.",
        confidence=0.95,
    )


def _resume() -> Resume:
    return Resume(
        full_name="Alex Candidate",
        email="alex@example.com",
        phone="555-0100",
        education=[
            Education(
                institution="State University",
                degree="Bachelor of Science",
                program="Cybersecurity",
            )
        ],
        certifications=[Certification(name="Security+", issuer="CompTIA")],
        skills=[
            Skill(name="Java"),
            Skill(name="Python"),
            Skill(name="Git"),
            Skill(name="Linux"),
            Skill(name="Networking"),
            Skill(name="Security+"),
            Skill(name="HTML"),
        ],
        projects=[
            Project(
                name="Portfolio Website",
                description="Created a personal portfolio.",
                bullets=["Built a personal portfolio with HTML."],
                technologies=["HTML"],
            ),
            Project(
                name="Packet Sniffer Project",
                description="Captured and analyzed network traffic.",
                bullets=[
                    "Built a Python packet sniffer to capture and analyze network traffic.",
                    "Documented packet fields and networking observations.",
                ],
                technologies=["Python", "Networking"],
            ),
            Project(
                name="Java Game",
                description="Built a small Java game.",
                bullets=["Developed game logic in Java."],
                technologies=["Java"],
            ),
        ],
        experience=[
            Experience(
                organization="Cafe",
                title="Team Member",
                start_date="2024",
                end_date="Present",
                bullets=["Helped customers during busy shifts."],
            ),
            Experience(
                organization="Campus IT",
                title="IT Assistant",
                start_date="2023",
                end_date="2024",
                bullets=["Supported students with Linux workstation issues."],
                technologies=["Linux"],
            ),
        ],
    )


def _profile() -> CandidateProfile:
    skills = ["Python", "Linux", "Networking", "Security+", "Git", "Java", "HTML"]
    return CandidateProfile(
        candidate_name="Alex Candidate",
        experience_level=ExperienceLevel.STUDENT,
        primary_domain=CandidateDomain.CYBERSECURITY,
        core_skills=skills,
        supporting_skills=["communication"],
        certifications=["Security+"],
        technologies=skills,
        target_roles=["SOC Analyst Intern"],
        education_level="Cybersecurity student",
        confidence_score=0.95,
        profile_summary="Cybersecurity student.",
        validation_status=ProfileValidationStatus.CLEAN,
    )


def _job() -> JobAnalysis:
    return JobAnalysis(
        job_id="soc-job",
        job_title="SOC Analyst Intern",
        company="Example Security",
        normalized_title="soc analyst intern",
        required_skills=[
            _requirement("Python", RequirementLevel.REQUIRED),
            _requirement("Linux", RequirementLevel.REQUIRED),
            _requirement("SIEM", RequirementLevel.REQUIRED),
        ],
        preferred_skills=[
            _requirement("Networking", RequirementLevel.PREFERRED),
            _requirement("Splunk", RequirementLevel.PREFERRED),
        ],
        certifications=["Security+"],
        ats_keywords=[
            "Python",
            "Linux",
            "Networking",
            "Security+",
            "network traffic analysis",
            "SIEM",
            "Splunk",
        ],
        soft_skills=["communication"],
        role_category=RoleCategory.CYBERSECURITY,
        domain_category=RoleCategory.CYBERSECURITY,
        seniority=JobSeniority.INTERNSHIP,
        confidence_score=0.95,
        raw_text_hash="hash",
        analysis_source=AnalysisSource.RULE_BASED,
    )


def _contracts(
    resume: Resume | None = None,
) -> tuple[Resume, CandidateProfile, JobAnalysis, SkillGapReport, ATSMatchReport]:
    source = resume or _resume()
    profile = _profile()
    job = _job()
    gap = SkillGapAnalyzer().analyze(profile, job)
    ats = ATSMatchScoringService().score(source, profile, job, gap)
    return source, profile, job, gap, ats


def _request(
    *,
    resume: Resume | None = None,
    options: ResumeOptimizationOptions | None = None,
) -> ResumeOptimizationRequest:
    source, profile, job, gap, ats = _contracts(resume)
    plan = ResumeOptimizationPlanner().create_plan(source, profile, job, gap, ats)
    return ResumeOptimizationRequest(
        resume=source,
        candidate_profile=profile,
        job_analysis=job,
        skill_gap_report=gap,
        ats_match_report=ats,
        optimization_plan=plan,
        options=options or ResumeOptimizationOptions(strict_mode=False),
    )


def _safe_packet_rewrite(request: BulletRewriteRequest) -> str:
    if request.original_bullet.startswith("Built a Python packet sniffer"):
        return (
            "Developed a Python packet sniffer to capture and analyze network traffic."
        )
    return request.original_bullet


def test_optimizes_cybersecurity_resume_for_soc_internship() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())

    assert result.optimized_resume.target_job_title == "SOC Analyst Intern"
    assert result.optimized_resume.projects[0].name == "Packet Sniffer Project"
    assert result.optimized_resume.skills[0].name in {"Python", "Linux"}


def test_reorders_skills_safely_without_adding_missing_skills() -> None:
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request())
    names = [skill.name for skill in result.optimized_resume.skills]

    assert names.index("Python") < names.index("Java")
    assert "SIEM" not in names
    assert "Splunk" not in names


def test_moves_relevant_project_higher() -> None:
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request())

    assert result.optimized_resume.projects[0].name == "Packet Sniffer Project"
    assert any(change.change_type == ChangeType.PROJECT_REORDERED for change in result.changes)


def test_rewrites_safe_packet_sniffer_bullet() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())

    assert result.optimized_resume.projects[0].bullets[0].startswith("Developed a Python")


def test_rejects_bullet_rewrite_containing_splunk() -> None:
    rewriter = MockBulletRewriter(lambda request: f"{request.original_bullet} Used Splunk.")
    result = FullResumeOptimizer(rewriter).optimize(_request())

    assert "Splunk" not in " ".join(result.optimized_resume.projects[0].bullets)
    assert result.safety_report.blocked_changes


def test_rejects_bullet_rewrite_containing_siem_claim() -> None:
    rewriter = MockBulletRewriter(lambda request: "Monitored SIEM alerts using Python.")
    result = FullResumeOptimizer(rewriter).optimize(_request())

    assert all(
        "SIEM" not in bullet
        for project in result.optimized_resume.projects
        for bullet in project.bullets
    )


def test_preserves_original_employer_role_and_dates() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())
    values = {
        (item.organization, item.title, item.start_date, item.end_date)
        for item in result.optimized_resume.experience
    }

    assert ("Cafe", "Team Member", "2024", "Present") in values
    assert ("Campus IT", "IT Assistant", "2023", "2024") in values


def test_does_not_invent_certifications() -> None:
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request())

    assert [item.name for item in result.optimized_resume.certifications] == ["Security+"]


def test_does_not_invent_structured_technologies() -> None:
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request())
    technologies = {
        technology
        for project in result.optimized_resume.projects
        for technology in project.technologies
    }

    assert technologies == {"HTML", "Python", "Networking", "Java"}


def test_rejects_invented_technology_in_bullet() -> None:
    rewriter = MockBulletRewriter(
        lambda request: f"{request.original_bullet} Implemented Spring Boot."
    )
    result = FullResumeOptimizer(rewriter).optimize(_request())

    assert "Spring Boot" not in str(result.optimized_resume.model_dump())


def test_rejects_invented_metric() -> None:
    rewriter = MockBulletRewriter(lambda request: f"{request.original_bullet} Improved by 40%.")
    result = FullResumeOptimizer(rewriter).optimize(_request())

    assert "40%" not in str(result.optimized_resume.model_dump())


def test_nontechnical_experience_remains_honest() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())
    cafe = next(item for item in result.optimized_resume.experience if item.organization == "Cafe")

    assert cafe.bullets == ["Helped customers during busy shifts."]


def test_summary_generated_only_from_safe_evidence() -> None:
    options = ResumeOptimizationOptions(include_summary=True, strict_mode=False)
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request(options=options))

    assert result.optimized_resume.summary
    assert "Splunk" not in result.optimized_resume.summary
    assert "SIEM" not in result.optimized_resume.summary


def test_strict_mode_blocks_unsafe_optimized_resume() -> None:
    options = ResumeOptimizationOptions(strict_mode=True)
    rewriter = MockBulletRewriter(lambda request: f"{request.original_bullet} Used Splunk.")
    request = _request(options=options)
    result = FullResumeOptimizer(rewriter).optimize(request)

    assert [skill.name for skill in result.optimized_resume.skills] == [
        skill.name for skill in request.resume.skills
    ]
    assert result.changes == []
    assert result.safety_report.blocked_changes


def test_non_strict_mode_removes_unsafe_change_and_continues() -> None:
    rewriter = MockBulletRewriter(
        lambda request: (
            f"{request.original_bullet} Used Splunk."
            if "packet sniffer" in request.original_bullet
            else request.original_bullet
        )
    )
    result = FullResumeOptimizer(rewriter).optimize(_request())

    assert result.optimized_resume.projects[0].name == "Packet Sniffer Project"
    assert "Splunk" not in str(result.optimized_resume.model_dump())


def test_one_page_constraints_trim_lower_priority_content() -> None:
    options = ResumeOptimizationOptions(
        max_projects=1,
        max_experiences=1,
        max_bullets_per_project=1,
        strict_mode=False,
    )
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request(options=options))

    assert len(result.optimized_resume.projects) == 1
    assert len(result.optimized_resume.experience) == 1
    assert any(change.change_type == ChangeType.SECTION_TRIMMED for change in result.changes)


def test_change_log_records_modifications() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())
    types = {change.change_type for change in result.changes}

    assert ChangeType.SKILL_REORDERED in types
    assert ChangeType.PROJECT_REORDERED in types
    assert ChangeType.BULLET_REWRITTEN in types


def test_safety_report_records_blocked_changes() -> None:
    result = FullResumeOptimizer(
        MockBulletRewriter(lambda request: f"{request.original_bullet} Used Splunk.")
    ).optimize(_request())

    assert result.safety_report.blocked_changes
    assert all(
        change.safety_status == SafetyStatus.BLOCKED
        for change in result.safety_report.blocked_changes
    )


def test_missing_project_section_is_handled() -> None:
    resume = _resume().model_copy(update={"projects": []})
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request(resume=resume))

    assert result.optimized_resume.projects == []


def test_missing_experience_section_is_handled() -> None:
    resume = _resume().model_copy(update={"experience": []})
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(_request(resume=resume))

    assert result.optimized_resume.experience == []


def test_estimated_score_improvement_is_conservative() -> None:
    request = _request()
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(request)

    assert (
        result.estimated_after_ats_score.high
        <= request.optimization_plan.expected_score_improvement.high
    )
    assert "not a guaranteed ATS outcome" in result.estimated_after_ats_score.rationale


def test_original_resume_is_not_mutated() -> None:
    request = _request()
    before = request.resume.model_dump()

    FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(request)

    assert request.resume.model_dump() == before


def test_all_rewritten_bullets_include_traceability() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())
    rewrites = [
        change
        for change in result.changes
        if change.change_type == ChangeType.BULLET_REWRITTEN
    ]

    assert rewrites
    assert all(change.item_name and change.reason and change.evidence for change in rewrites)


def test_optimized_resume_preserves_contact_and_education() -> None:
    request = _request()
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(request)

    assert result.optimized_resume.contact.email == request.resume.email
    assert result.optimized_resume.education == request.resume.education


def test_unsafe_keywords_remain_missing() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(_request())
    text = str(result.optimized_resume.model_dump())

    assert "Splunk" not in text
    assert "SIEM" not in text


def test_forbidden_claims_are_enforced_globally() -> None:
    result = FullResumeOptimizer(
        MockBulletRewriter(lambda request: f"{request.original_bullet} Used Splunk.")
    ).optimize(_request())

    assert "Used Splunk" not in str(result.optimized_resume.model_dump())


def test_bullet_rewriter_failure_preserves_original_and_continues() -> None:
    result = FullResumeOptimizer(MockBulletRewriter(error=RuntimeError("provider down"))).optimize(
        _request()
    )

    assert result.optimized_resume.projects
    assert any("provider down" in warning for warning in result.warnings)


def test_preserve_original_order_disables_reordering() -> None:
    options = ResumeOptimizationOptions(preserve_original_order=True, strict_mode=False)
    request = _request(options=options)
    result = FullResumeOptimizer(MockBulletRewriter()).optimize(request)

    assert [item.name for item in result.optimized_resume.projects] == [
        item.name for item in request.resume.projects
    ]
    assert [item.name for item in result.optimized_resume.skills] == [
        item.name for item in request.resume.skills
    ]
