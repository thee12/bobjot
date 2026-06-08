"""Tests for the resume validation engine."""

import copy

import pytest

from ai_internship_assistant.domain.models import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
    Skill,
    ValidationCategory,
    ValidationSeverity,
)
from ai_internship_assistant.services.resume_validation import (
    ResumeValidationError,
    ResumeValidator,
)
from ai_internship_assistant.utils import normalize_skill_name


def _perfect_resume() -> Resume:
    """Return a complete resume with no expected validation issues."""

    return Resume(
        full_name="Alex Morgan",
        email="alex.morgan@example.com",
        phone="555-0101",
        linkedin_url="https://www.linkedin.com/in/alexmorgan",
        github_url="https://github.com/alexmorgan",
        education=[
            Education(
                institution="State University",
                degree="Bachelor of Science",
                program="Computer Science",
                end_date="2026",
            )
        ],
        experience=[
            Experience(
                organization="Northwind Labs",
                title="Software Engineering Intern",
                bullets=["Built endpoint tests for an internal scheduling API."],
                technologies=["Java", "Spring Boot"],
            )
        ],
        projects=[
            Project(
                name="Course Scheduler",
                description="Scheduling tool for student project teams.",
                bullets=["Built a scheduling workflow for class teams."],
                technologies=["Python", "FastAPI"],
            )
        ],
        certifications=[Certification(name="CompTIA A+", issuer="CompTIA")],
        skills=[
            Skill(name="Python", category="programming language"),
            Skill(name="FastAPI", category="framework"),
            Skill(name="Git", category="tool"),
        ],
    )


def _messages_by_category(report_category: ValidationCategory, resume: Resume) -> list[str]:
    report = ResumeValidator().validate(resume)
    return [issue.message for issue in report.issues if issue.category == report_category]


def test_perfect_resume_has_no_issues_and_remains_valid() -> None:
    """A complete, internally consistent resume should produce a clean report."""

    resume = _perfect_resume()
    before = copy.deepcopy(resume)

    report = ResumeValidator().validate(resume)

    assert report.issues == []
    assert report.warning_count == 0
    assert report.error_count == 0
    assert report.info_count == 0
    assert report.is_valid
    assert resume == before


def test_missing_email_generates_contact_warning() -> None:
    """Missing email should be reported without invalidating the resume."""

    resume = _perfect_resume().model_copy(update={"email": None})

    report = ResumeValidator().validate(resume)

    assert report.is_valid
    assert any(issue.field_name == "email" for issue in report.issues)
    assert report.warning_count == 1


def test_duplicate_skills_use_normalization_and_detect_capitalization() -> None:
    """Python3, Python 3, and python should compare as the same skill."""

    resume = _perfect_resume().model_copy(
        update={
            "skills": [
                Skill(name="Python3", category="programming language"),
                Skill(name="Python 3", category="programming language"),
                Skill(name="python", category="programming language"),
            ]
        }
    )

    report = ResumeValidator().validate(resume)

    assert any("Duplicate skill" in issue.message for issue in report.issues)
    assert any("capitalization" in issue.message for issue in report.issues)


def test_duplicate_projects_are_reported() -> None:
    """Duplicate project names should produce project warnings."""

    project = Project(
        name="Course Scheduler",
        description="Scheduling tool for student project teams.",
        technologies=["Python"],
    )
    resume = _perfect_resume().model_copy(update={"projects": [project, project]})

    report = ResumeValidator().validate(resume)

    assert any(issue.category == ValidationCategory.PROJECT for issue in report.issues)
    assert any("Duplicate project name" in issue.message for issue in report.issues)


def test_missing_education_is_reported() -> None:
    """No education section should produce a warning."""

    resume = _perfect_resume().model_copy(update={"education": []})

    report = ResumeValidator().validate(resume)

    assert any(issue.field_name == "education" for issue in report.issues)
    assert report.warning_count == 1


def test_resume_with_no_experience_gets_info_only() -> None:
    """No internship experience should be informational, not invalid."""

    resume = _perfect_resume().model_copy(update={"experience": []})

    report = ResumeValidator().validate(resume)

    assert report.is_valid
    assert report.error_count == 0
    assert any(issue.severity == ValidationSeverity.INFO for issue in report.issues)


def test_empty_resume_gets_error_report() -> None:
    """A completely empty partially parsed resume should be reported as invalid."""

    resume = Resume.model_construct()

    report = ResumeValidator().validate(resume)

    assert not report.is_valid
    assert report.error_count == 1
    assert any("completely empty" in issue.message for issue in report.issues)


def test_malformed_profile_urls_are_reported() -> None:
    """Malformed LinkedIn and GitHub URLs should produce contact warnings."""

    resume = _perfect_resume().model_copy(
        update={
            "linkedin_url": "linkedin.com/in/alexmorgan",
            "github_url": "https://not-github.example.com/alexmorgan",
        }
    )

    report = ResumeValidator().validate(resume)

    assert report.warning_count == 2
    assert all(issue.category == ValidationCategory.CONTACT for issue in report.issues)


def test_malformed_email_is_reported() -> None:
    """Malformed extracted email should be reported without throwing."""

    resume = _perfect_resume().model_copy(update={"email": "not-an-email"})

    report = ResumeValidator().validate(resume)

    assert report.is_valid
    assert any(issue.field_name == "email" for issue in report.issues)


def test_duplicate_certifications_are_reported() -> None:
    """Duplicate certification names should produce certification warnings."""

    resume = _perfect_resume().model_copy(
        update={
            "certifications": [
                Certification(name="CompTIA A+", issuer="CompTIA"),
                Certification(name="comptia a+", issuer="CompTIA"),
            ]
        }
    )

    report = ResumeValidator().validate(resume)

    assert any(issue.category == ValidationCategory.CERTIFICATION for issue in report.issues)
    assert any("Duplicate certification" in issue.message for issue in report.issues)


def test_missing_optional_profiles_and_certifications_are_info_only() -> None:
    """No GitHub, LinkedIn, or certifications should not fail validation."""

    resume = _perfect_resume().model_copy(
        update={
            "linkedin_url": None,
            "github_url": None,
            "certifications": [],
        }
    )

    report = ResumeValidator().validate(resume)

    assert report.is_valid
    assert report.error_count == 0
    assert report.warning_count == 0
    assert report.info_count == 3


def test_partial_resume_with_missing_nested_fields_is_reported() -> None:
    """Malformed partially parsed nested entries should produce report issues."""

    resume = _perfect_resume().model_copy(
        update={
            "education": [Education.model_construct(institution=None, degree=None)],
            "projects": [Project.model_construct(name=None, description=None, technologies=[])],
            "experience": [
                Experience.model_construct(
                    organization=None,
                    title=None,
                    bullets=[],
                    technologies=[],
                )
            ],
        }
    )

    report = ResumeValidator().validate(resume)
    messages = [issue.message for issue in report.issues]

    assert any("school name" in message for message in messages)
    assert any("Project entry is missing a title" in message for message in messages)
    assert any("missing a company" in message for message in messages)
    assert report.is_valid


def test_impossible_graduation_year_is_reported() -> None:
    """Impossible education years should generate education warnings."""

    resume = _perfect_resume().model_copy(
        update={
            "education": [
                Education(
                    institution="State University",
                    degree="Bachelor of Science",
                    end_date="2099",
                )
            ]
        }
    )

    messages = _messages_by_category(ValidationCategory.EDUCATION, resume)

    assert any("impossible graduation year" in message for message in messages)


def test_duplicate_technologies_are_reported() -> None:
    """Repeated technologies across projects and experience should be detected."""

    resume = _perfect_resume().model_copy(
        update={
            "projects": [
                Project(
                    name="Course Scheduler",
                    description="Scheduling tool.",
                    technologies=["Python 3"],
                )
            ],
            "experience": [
                Experience(
                    organization="Northwind Labs",
                    title="Intern",
                    bullets=["Built tests."],
                    technologies=["python"],
                )
            ],
        }
    )

    report = ResumeValidator().validate(resume)

    assert any("Duplicate technology" in issue.message for issue in report.issues)


def test_unusually_large_project_generates_format_warning() -> None:
    """A very large project blob should look suspicious to downstream modules."""

    resume = _perfect_resume().model_copy(
        update={
            "projects": [
                Project(
                    name="Merged Project Blob",
                    description="word " * 3_001,
                    technologies=["Python"],
                )
            ]
        }
    )

    report = ResumeValidator().validate(resume)

    assert any(issue.category == ValidationCategory.FORMAT for issue in report.issues)


def test_validator_rejects_null_resume_as_programmer_error() -> None:
    """Calling validate with None should raise a meaningful programmer-error exception."""

    with pytest.raises(ResumeValidationError):
        ResumeValidator().validate(None)  # type: ignore[arg-type]


def test_skill_normalization_utility_is_reusable() -> None:
    """Common skill aliases should normalize consistently for comparisons."""

    assert normalize_skill_name("Python3") == "Python"
    assert normalize_skill_name("Python 3") == "Python"
    assert normalize_skill_name("python") == "Python"
    assert normalize_skill_name("Github") == "GitHub"

