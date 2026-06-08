"""Tests for deterministic candidate profile generation."""

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    Certification,
    Education,
    Experience,
    ExperienceLevel,
    ProfileValidationStatus,
    Project,
    Resume,
    Skill,
)
from ai_internship_assistant.services.candidate_profile_generator import (
    CandidateProfileGenerator,
    CandidateProfilePipeline,
)
from ai_internship_assistant.services.resume_validation import ResumeValidator


def _resume(
    *,
    skills: list[str],
    certifications: list[str] | None = None,
    projects: list[Project] | None = None,
    experience: list[Experience] | None = None,
) -> Resume:
    """Build a complete base resume for focused profile classification tests."""

    return Resume(
        full_name="Example Candidate",
        email="candidate@example.com",
        phone="555-0101",
        linkedin_url="https://www.linkedin.com/in/example",
        github_url="https://github.com/example",
        education=[
            Education(
                institution="State University",
                degree="Bachelor of Science",
                program="Computer Science",
                end_date="2026",
            )
        ],
        skills=[Skill(name=skill) for skill in skills],
        certifications=[
            Certification(name=certification) for certification in (certifications or [])
        ],
        projects=projects or [],
        experience=experience or [],
    )


def test_generates_cybersecurity_student_profile() -> None:
    """Cybersecurity evidence should produce security-focused classifications."""

    resume = _resume(
        skills=["Python", "Linux", "Networking"],
        certifications=["Security+"],
        projects=[
            Project(
                name="Network Security Lab",
                description="Documented network security findings.",
                technologies=["Python", "Linux"],
            )
        ],
    )

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.CYBERSECURITY
    assert profile.experience_level == ExperienceLevel.STUDENT
    assert "Cybersecurity Intern" in profile.target_roles
    assert profile.certifications == ["Security+"]
    assert set(profile.core_skills) == {"Python", "Linux", "Networking"}


def test_generates_software_engineering_student_profile() -> None:
    """Software development evidence should produce engineering roles."""

    resume = _resume(
        skills=["Python", "FastAPI", "Git"],
        projects=[
            Project(
                name="Scheduling API",
                description="Built an API for a software engineering course.",
                technologies=["Python", "FastAPI"],
            )
        ],
    )

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.SOFTWARE_ENGINEERING
    assert "Software Engineering Intern" in profile.search_keywords
    assert "Git" in profile.supporting_skills
    assert "Python" in profile.core_skills


def test_generates_networking_student_profile() -> None:
    """Networking evidence should produce network operations roles."""

    resume = _resume(
        skills=["Networking", "Cisco", "Routing", "GitHub"],
        certifications=["CCNA"],
    )

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.NETWORKING
    assert "Network Operations Intern" in profile.target_roles
    assert "GitHub" in profile.supporting_skills


def test_resume_with_no_certifications_does_not_invent_any() -> None:
    """Profiles must preserve an empty certification list."""

    resume = _resume(skills=["Python", "FastAPI"], certifications=[])

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.certifications == []
    assert profile.validation_status == ProfileValidationStatus.CLEAN
    assert any(
        "does not include certifications" in message for message in profile.validation_messages
    )


def test_resume_with_no_projects_degrades_gracefully() -> None:
    """Profiles should generate successfully when the source has no projects."""

    resume = _resume(skills=["Python", "Java"], projects=[])

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.SOFTWARE_ENGINEERING
    assert profile.confidence_score < 1.0
    assert profile.technologies == ["Python", "Java"]


def test_resume_with_minimal_skills_uses_general_domain() -> None:
    """A skill without domain evidence should not trigger an invented specialization."""

    resume = _resume(skills=["Excel"])

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.GENERAL_TECHNOLOGY
    assert profile.target_roles == ["Technology Intern"]
    assert profile.core_skills == ["Excel"]


def test_resume_with_mixed_domains_has_secondary_domains() -> None:
    """Mixed evidence should preserve a primary domain and useful secondary domains."""

    resume = _resume(
        skills=["Python", "FastAPI", "Networking"],
        certifications=["Security+"],
        projects=[
            Project(
                name="Secure API",
                description="Built an API and documented network security controls.",
                technologies=["Python", "FastAPI"],
            )
        ],
    )

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.primary_domain == CandidateDomain.SOFTWARE_ENGINEERING
    assert CandidateDomain.CYBERSECURITY in profile.secondary_domains
    assert CandidateDomain.NETWORKING in profile.secondary_domains


def test_resume_with_explicit_senior_experience_is_classified_senior() -> None:
    """Experience level should use explicit titles rather than estimated years."""

    resume = _resume(
        skills=["Python", "Java"],
        experience=[
            Experience(
                organization="Northwind Labs",
                title="Senior Software Engineer",
                bullets=["Led development of an internal API."],
                technologies=["Python"],
            ),
            Experience(
                organization="Contoso",
                title="Software Engineer",
                bullets=["Built Java services."],
                technologies=["Java"],
            ),
        ],
    )

    profile = CandidateProfileGenerator().generate(resume)

    assert profile.experience_level == ExperienceLevel.SENIOR
    assert profile.primary_domain == CandidateDomain.SOFTWARE_ENGINEERING


def test_validation_errors_lower_confidence_and_flow_into_profile() -> None:
    """Validation status and messages should be carried into generated profiles."""

    resume = Resume.model_construct(
        full_name=None,
        email=None,
        phone=None,
        linkedin_url=None,
        github_url=None,
        links=[],
        summary=None,
        education=[],
        experience=[],
        projects=[],
        certifications=[],
        skills=[],
    )
    report = ResumeValidator().validate(resume)

    profile = CandidateProfileGenerator().generate(resume, report)

    assert profile.validation_status == ProfileValidationStatus.HAS_ERRORS
    assert profile.confidence_score < 0.35
    assert profile.validation_messages


def test_profile_pipeline_returns_profile_and_validation_report() -> None:
    """The pipeline should expose both outputs independently."""

    resume = _resume(skills=["Python", "FastAPI"])

    result = CandidateProfilePipeline().run(resume)

    assert result.profile.primary_domain == CandidateDomain.SOFTWARE_ENGINEERING
    assert result.validation_report.is_valid
