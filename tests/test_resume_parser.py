"""Tests for LLM-backed resume parsing boundaries."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_internship_assistant.domain.models import (
    Education,
    Experience,
    Project,
    Resume,
    Skill,
)
from ai_internship_assistant.services.resume_parser import (
    EmptyResumeTextError,
    MalformedLLMResponseError,
    OpenAIResumeParser,
)
from ai_internship_assistant.services.resume_validation import (
    ResumeValidationWarningCode,
    ResumeValidator,
)

DATA_DIR = Path(__file__).parent / "data"


class FakeResponsesClient:
    """Fake OpenAI responses client that returns prebuilt structured output."""

    def __init__(self, resume: Resume | None) -> None:
        self.resume = resume
        self.calls: list[dict[str, object]] = []

    def parse(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs)
        return SimpleNamespace(output_parsed=self.resume)


class FakeOpenAIClient:
    """Small test double matching the OpenAI client surface used by the parser."""

    def __init__(self, resume: Resume | None) -> None:
        self.responses = FakeResponsesClient(resume)


def _fixture_text(name: str) -> str:
    return (DATA_DIR / name).read_text(encoding="utf-8")


def test_parse_simple_one_page_resume() -> None:
    """The parser should return a structured Resume for a simple one-page input."""

    expected_resume = Resume(
        full_name="Alex Morgan",
        email="alex.morgan@example.com",
        linkedin_url="https://www.linkedin.com/in/alexmorgan",
        github_url="https://github.com/alexmorgan",
        education=[Education(institution="State University", degree="B.S. Computer Science")],
        projects=[
            Project(
                name="Course Scheduler",
                bullets=["Built a scheduling tool for student project teams."],
                technologies=["Python", "FastAPI"],
            )
        ],
        skills=[
            Skill(name="Python", category="programming language"),
            Skill(name="SQL", category="programming language"),
            Skill(name="FastAPI", category="framework"),
        ],
    )
    client = FakeOpenAIClient(expected_resume)

    resume = OpenAIResumeParser(client=client).parse(_fixture_text("simple_one_page_resume.txt"))

    assert resume == expected_resume
    assert client.responses.calls[0]["text_format"] is Resume
    assert client.responses.calls[0]["temperature"] == 0.0


def test_parse_two_page_resume() -> None:
    """The parser should accept longer raw text from a multi-page resume."""

    expected_resume = Resume(
        full_name="Jordan Lee",
        email="jordan.lee@example.com",
        education=[Education(institution="Central College", degree="B.S. Information Systems")],
        experience=[
            Experience(
                organization="Northwind Labs",
                title="IT Support Intern",
                start_date="May 2024",
                end_date="August 2024",
                bullets=["Resolved help desk tickets for internal users."],
            )
        ],
        projects=[Project(name="Inventory Dashboard", technologies=["React", "Flask", "SQLite"])],
        skills=[Skill(name="Python", category="programming language")],
    )

    resume = OpenAIResumeParser(client=FakeOpenAIClient(expected_resume)).parse(
        _fixture_text("two_page_resume.txt")
    )

    assert resume.full_name == "Jordan Lee"
    assert resume.experience[0].title == "IT Support Intern"


def test_parse_resume_with_multiple_projects() -> None:
    """The parser should preserve multiple distinct projects."""

    expected_resume = Resume(
        full_name="Priya Shah",
        email="priya.shah@example.com",
        education=[Education(institution="Metro University", degree="B.S. Data Science")],
        projects=[
            Project(name="Housing Price Analysis", technologies=["Python", "pandas", "Jupyter"]),
            Project(name="Campus Events Explorer", technologies=["Streamlit", "SQLite"]),
        ],
        skills=[Skill(name="Python", category="programming language")],
    )

    resume = OpenAIResumeParser(client=FakeOpenAIClient(expected_resume)).parse(
        _fixture_text("multiple_projects_resume.txt")
    )

    assert [project.name for project in resume.projects] == [
        "Housing Price Analysis",
        "Campus Events Explorer",
    ]


def test_parse_resume_with_internship_experience() -> None:
    """The parser should extract internship experience and technologies."""

    expected_resume = Resume(
        full_name="Taylor Kim",
        email="taylor.kim@example.com",
        education=[
            Education(
                institution="Pacific Technical Institute",
                degree="B.S. Software Engineering",
            )
        ],
        experience=[
            Experience(
                organization="Contoso Health",
                title="Software Engineering Intern",
                start_date="June 2025",
                end_date="August 2025",
                bullets=["Implemented API endpoint tests for appointment scheduling services."],
                technologies=["Java", "Spring Boot", "Postman"],
            )
        ],
        skills=[Skill(name="Java", category="programming language")],
    )

    resume = OpenAIResumeParser(client=FakeOpenAIClient(expected_resume)).parse(
        _fixture_text("internship_experience_resume.txt")
    )

    assert resume.experience[0].organization == "Contoso Health"
    assert "Spring Boot" in resume.experience[0].technologies


def test_parse_resume_with_no_experience() -> None:
    """The parser should allow resumes with education, projects, and no experience."""

    expected_resume = Resume(
        full_name="Sam Rivera",
        email="sam.rivera@example.com",
        education=[Education(institution="Lakeside College", degree="B.S. Computer Science")],
        projects=[Project(name="Personal Budget CLI", technologies=["Python"])],
        skills=[Skill(name="Python", category="programming language")],
    )

    resume = OpenAIResumeParser(client=FakeOpenAIClient(expected_resume)).parse(
        _fixture_text("no_experience_resume.txt")
    )

    assert resume.experience == []
    assert resume.projects[0].name == "Personal Budget CLI"


def test_parse_resume_with_unusual_formatting() -> None:
    """The parser should accept unusual raw text formatting."""

    expected_resume = Resume(
        full_name="RILEY PATEL",
        email="riley.patel@example.com",
        github_url="https://github.com/rileypatel",
        education=[Education(institution="Urban University", degree="B.A. Digital Technology")],
        experience=[
            Experience(
                organization="Urban University Lab",
                title="Research Assistant",
                start_date="Jan 2024",
                end_date="May 2024",
                bullets=["Cleaned survey exports for a student research project."],
                technologies=["Python"],
            )
        ],
        projects=[Project(name="Portfolio Site", technologies=["JavaScript", "Node.js"])],
        skills=[Skill(name="Node.js", category="framework")],
    )

    resume = OpenAIResumeParser(client=FakeOpenAIClient(expected_resume)).parse(
        _fixture_text("unusual_formatting_resume.txt")
    )

    assert resume.full_name == "RILEY PATEL"
    assert resume.projects[0].technologies == ["JavaScript", "Node.js"]


def test_empty_resume_text_is_rejected() -> None:
    """Whitespace-only input should not be sent to the LLM."""

    with pytest.raises(EmptyResumeTextError):
        OpenAIResumeParser(client=FakeOpenAIClient(None)).parse("   \n\t")


def test_malformed_llm_response_is_rejected() -> None:
    """A response without a parsed Resume should raise a parser-specific error."""

    with pytest.raises(MalformedLLMResponseError):
        OpenAIResumeParser(client=FakeOpenAIClient(None)).parse("Alex Morgan")


def test_resume_validator_returns_non_blocking_warnings() -> None:
    """Validation issues should be reported without preventing Resume construction."""

    resume = Resume(
        email="not-an-email",
        github_url="github.com/example",
        links=["https://valid.example.com", "not-a-url"],
        skills=[
            Skill(name="Python", category="programming language"),
            Skill(name="python", category="programming language"),
        ],
    )

    warnings = ResumeValidator().validate(resume)
    warning_codes = {warning.code for warning in warnings}

    assert ResumeValidationWarningCode.MISSING_NAME in warning_codes
    assert ResumeValidationWarningCode.MISSING_EDUCATION in warning_codes
    assert ResumeValidationWarningCode.DUPLICATE_SKILL in warning_codes
    assert ResumeValidationWarningCode.MALFORMED_EMAIL in warning_codes
    assert ResumeValidationWarningCode.MALFORMED_URL in warning_codes

