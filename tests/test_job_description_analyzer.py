"""Tests for conservative deterministic job-description analysis."""

from pathlib import Path

import pytest

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobPosting,
    JobSourceType,
    RequirementLevel,
    RoleCategory,
)
from ai_internship_assistant.services import RuleBasedJobDescriptionAnalyzer

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "job_descriptions"


def _fixture(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


def _job(
    *,
    title: str,
    description: str | None = None,
    requirements: list[str] | None = None,
    preferred_qualifications: list[str] | None = None,
    technologies: list[str] | None = None,
    certifications: list[str] | None = None,
    employment_type: EmploymentType = EmploymentType.INTERNSHIP,
    raw_data: dict[str, object] | None = None,
) -> JobPosting:
    return JobPosting(
        id=title.casefold().replace(" ", "-"),
        source=JobSourceType.MOCK,
        source_name="Mock",
        title=title,
        company="Example Company",
        employment_type=employment_type,
        description=description,
        requirements=requirements or [],
        preferred_qualifications=preferred_qualifications or [],
        technologies=technologies or [],
        certifications=certifications or [],
        raw_data=raw_data or {},
    )


def _levels(analysis: object, attribute: str) -> dict[str, RequirementLevel]:
    requirements = getattr(analysis, attribute)
    return {requirement.name: requirement.requirement_level for requirement in requirements}


@pytest.mark.parametrize(
    ("fixture_name", "title", "expected_category", "expected_term"),
    [
        (
            "cybersecurity_internship.txt",
            "Cybersecurity Intern",
            RoleCategory.CYBERSECURITY,
            "incident response",
        ),
        (
            "soc_analyst_internship.txt",
            "SOC Analyst Intern",
            RoleCategory.CYBERSECURITY,
            "SOC",
        ),
        (
            "software_engineering_internship.txt",
            "Software Engineering Intern",
            RoleCategory.SOFTWARE_ENGINEERING,
            "Python",
        ),
        (
            "networking_internship.txt",
            "Network Engineering Intern",
            RoleCategory.NETWORKING,
            "network security",
        ),
    ],
)
def test_analyzes_representative_internship_fixtures(
    fixture_name: str,
    title: str,
    expected_category: RoleCategory,
    expected_term: str,
) -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title=title, description=_fixture(fixture_name))
    )

    extracted = {
        *analysis.programming_languages,
        *analysis.technical_tools,
        *analysis.cybersecurity_terms,
    }
    assert analysis.role_category == expected_category
    assert expected_term in extracted
    assert analysis.responsibilities
    assert analysis.qualifications
    assert analysis.confidence_score > 0.5


def test_senior_security_role_exposes_disqualifying_requirements() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Senior Security Architect",
            description=_fixture("senior_security_role.txt"),
        )
    )

    assert set(analysis.seniority_indicators) == {"architect", "senior"}
    assert "requires security clearance" in analysis.disqualifying_requirements
    assert "requires 5+ years of experience" in analysis.disqualifying_requirements
    assert "requires Master's degree" in analysis.disqualifying_requirements
    assert "likely senior role" in analysis.warnings


def test_security_plus_required_and_preferred_are_distinguished() -> None:
    analyzer = RuleBasedJobDescriptionAnalyzer()
    required = analyzer.analyze(
        _job(title="Security Intern", requirements=["CompTIA Security+ required."])
    )
    preferred = analyzer.analyze(
        _job(title="Security Intern", preferred_qualifications=["Security+ preferred."])
    )

    assert _levels(required, "required_skills")["Security+"] == RequirementLevel.REQUIRED
    assert _levels(preferred, "preferred_skills")["Security+"] == RequirementLevel.PREFERRED


def test_clearance_requirement_is_reported_conservatively() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="Security Analyst", description="Must hold an active Secret clearance.")
    )

    assert analysis.disqualifying_requirements == ["requires security clearance"]


def test_html_description_is_cleaned_and_sections_are_preserved() -> None:
    description = """
    <h2>Responsibilities</h2><ul><li>Monitor SIEM alerts.</li></ul>
    <h2>Required Qualifications</h2><ul><li>Python and Linux required.</li></ul>
    """

    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="SOC Intern", description=description)
    )

    assert analysis.responsibilities == ["Monitor SIEM alerts."]
    assert analysis.qualifications == ["Python and Linux required."]
    assert set(_levels(analysis, "required_skills")) >= {"Python", "Linux"}
    assert "SIEM" in analysis.cybersecurity_terms


def test_empty_description_returns_low_confidence_analysis_with_warnings() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(_job(title="Unknown Intern"))

    assert analysis.summary is None
    assert analysis.confidence_score == 0.1
    assert {"empty description", "no skills detected", "no responsibilities detected"} <= set(
        analysis.warnings
    )


def test_description_with_no_known_skills_does_not_invent_any() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="Student Intern", description="Help the team with assigned tasks.")
    )

    assert analysis.required_skills == []
    assert analysis.preferred_skills == []
    assert analysis.programming_languages == []
    assert analysis.technical_tools == []
    assert "no skills detected" in analysis.warnings


def test_repeated_keywords_are_deduplicated_but_ranked_for_ats() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Python Intern",
            description="Python Python Python. Use Git and Python. Git is required.",
        )
    )

    assert analysis.programming_languages == ["Python"]
    assert analysis.technical_tools == ["Git"]
    assert analysis.ats_keywords.count("Python") == 1
    assert analysis.ats_keywords.index("Python") < analysis.ats_keywords.index("Git")


def test_structured_required_and_preferred_sections_drive_requirement_levels() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Software Intern",
            requirements=["Python and Git are required."],
            preferred_qualifications=["Exposure to Docker and AWS."],
        )
    )

    assert set(_levels(analysis, "required_skills")) >= {"Python", "Git"}
    assert set(_levels(analysis, "preferred_skills")) >= {"Docker", "AWS"}


def test_experience_and_education_requirements_are_extracted_verbatim() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Security Intern",
            description=(
                "Requires 2+ years of relevant experience. "
                "Currently pursuing a bachelor's degree in cybersecurity."
            ),
        )
    )

    assert analysis.experience_requirements == ["2+ years of relevant experience"]
    assert any("bachelor's degree" in item for item in analysis.education_requirements)


def test_internship_and_seniority_indicators_come_from_explicit_evidence() -> None:
    intern = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="Cloud Intern", description="University program for current students.")
    )
    senior = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="Lead Cloud Architect", description="Design AWS systems.")
    )

    assert set(intern.internship_indicators) >= {"intern", "student", "university program"}
    assert senior.seniority_indicators == ["architect", "lead"]


def test_ats_keywords_prioritize_title_and_repeated_explicit_terms() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="SOC Analyst Intern",
            description="Splunk and SIEM monitoring. Splunk supports SIEM log analysis.",
        )
    )

    assert analysis.ats_keywords[0] == "SOC Analyst Intern"
    assert analysis.ats_keywords.index("Splunk") < analysis.ats_keywords.index("log analysis")
    assert len(analysis.ats_keywords) == len(
        {keyword.casefold() for keyword in analysis.ats_keywords}
    )


def test_punctuation_heavy_terms_do_not_create_false_matches() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(title="Software Intern", description="Collaborate and communicate with the team.")
    )

    assert "C" not in analysis.programming_languages
    assert "C++" not in analysis.programming_languages
    assert "C#" not in analysis.programming_languages
    assert "Security+" not in analysis.certifications


def test_structured_provider_terms_are_retained_without_description() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Software Intern",
            technologies=["Terraform"],
            certifications=["Vendor Cloud Associate"],
        )
    )

    assert "Terraform" in analysis.technical_tools
    assert "Vendor Cloud Associate" in analysis.certifications
    assert analysis.required_skills == []
    assert analysis.preferred_skills == []


def test_analysis_does_not_mutate_job_posting() -> None:
    job = _job(
        title="Cybersecurity Intern",
        description="<p>Use Python and Linux.</p>",
        technologies=["Python"],
    )
    before = job.model_dump()

    RuleBasedJobDescriptionAnalyzer().analyze(job)

    assert job.model_dump() == before


def test_selected_raw_data_text_is_used_when_normalized_description_is_sparse() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Security Intern",
            raw_data={
                "content": "<p>Support incident response with Splunk.</p>",
                "unrelated": {"internal_id": 42},
            },
        )
    )

    assert "incident response" in analysis.cybersecurity_terms
    assert "Splunk" in analysis.technical_tools


def test_preferred_experience_is_not_flagged_as_disqualifying() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Security Intern",
            preferred_qualifications=["5+ years of experience preferred."],
        )
    )

    assert "requires 5+ years of experience" not in analysis.disqualifying_requirements


def test_unknown_employment_type_generates_warning() -> None:
    analysis = RuleBasedJobDescriptionAnalyzer().analyze(
        _job(
            title="Security Analyst",
            description="Monitor SIEM alerts.",
            employment_type=EmploymentType.UNKNOWN,
        )
    )

    assert "unclear employment type" in analysis.warnings
