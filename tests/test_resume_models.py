"""Unit tests for resume domain model construction and validation."""

import pytest
from pydantic import ValidationError

from ai_internship_assistant.domain.models import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
    Skill,
)


def test_resume_constructs_with_nested_sections() -> None:
    """A complete resume should construct nested strongly typed models."""

    resume = Resume(
        full_name="Example Candidate",
        email="candidate@example.com",
        education=[
            Education(
                institution="State University",
                degree="Bachelor of Science",
                program="Computer Science",
                start_date="2022",
                end_date="2026",
                details=["Dean's List"],
            )
        ],
        experience=[
            Experience(
                organization="Campus IT",
                title="Student Support Technician",
                start_date="2024-01",
                end_date="Present",
                bullets=["Resolved workstation issues for students and staff"],
                technologies=["Python", "Windows"],
            )
        ],
        projects=[
            Project(
                name="Resume Matcher",
                description="Course project for matching resumes to job descriptions",
                bullets=["Compared resume skills against job posting requirements"],
                technologies=["Python"],
                links=["https://example.com/resume-matcher"],
            )
        ],
        certifications=[
            Certification(
                name="CompTIA A+",
                issuer="CompTIA",
                issued_date="2024",
            )
        ],
        skills=[
            Skill(name="Python", category="language"),
            Skill(name="FastAPI", category="framework"),
        ],
    )

    assert resume.full_name == "Example Candidate"
    assert resume.education[0].institution == "State University"
    assert resume.experience[0].technologies == ["Python", "Windows"]
    assert resume.projects[0].links == ["https://example.com/resume-matcher"]
    assert resume.certifications[0].issuer == "CompTIA"
    assert resume.skills[0].name == "Python"


def test_model_fields_strip_surrounding_whitespace() -> None:
    """String fields should normalize surrounding whitespace on construction."""

    resume = Resume(
        full_name="  Example Candidate  ",
        skills=[Skill(name="  Python  ", category="  language  ")],
    )

    assert resume.full_name == "Example Candidate"
    assert resume.skills[0].name == "Python"
    assert resume.skills[0].category == "language"


def test_empty_required_fields_are_rejected() -> None:
    """Required model identity fields should not accept blank strings."""

    with pytest.raises(ValidationError):
        Skill(name=" ")

    with pytest.raises(ValidationError):
        Education(institution="")

    with pytest.raises(ValidationError):
        Experience(organization="Campus IT", title=" ")

    with pytest.raises(ValidationError):
        Project(name="")

    with pytest.raises(ValidationError):
        Certification(name=" ")


def test_invalid_email_is_rejected() -> None:
    """Resume contact email should be rejected when malformed."""

    with pytest.raises(ValidationError):
        Resume(full_name="Example Candidate", email="not-an-email")


def test_resume_requires_some_content() -> None:
    """A resume object should not be constructible with no content at all."""

    with pytest.raises(ValidationError):
        Resume()


def test_extra_fields_are_rejected() -> None:
    """Unexpected keys should fail fast instead of silently entering the domain model."""

    with pytest.raises(ValidationError):
        Skill(name="Python", years=2)

