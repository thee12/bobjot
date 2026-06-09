"""Tests for deterministic ATS-friendly Markdown resume rendering."""

from pathlib import Path

import pytest

from ai_internship_assistant.domain.models import (
    BulletStyle,
    Certification,
    Education,
    Experience,
    HeadingStyle,
    OptimizedResume,
    Project,
    Resume,
    ResumeOutputFormat,
    ResumeRenderOptions,
    Skill,
)
from ai_internship_assistant.services import (
    FullResumeOptimizer,
    MarkdownResumeRenderer,
    ResumeOutputFileExistsError,
    UnsupportedResumeFormatError,
)
from ai_internship_assistant.utils import generate_resume_filename, sanitize_filename
from tests.test_full_resume_optimizer import MockBulletRewriter, _request, _safe_packet_rewrite


def _resume() -> Resume:
    return Resume(
        full_name="Daniel Flores",
        email="daniel@example.com",
        phone="555-0100",
        location="Raleigh, NC",
        linkedin_url="linkedin.com/in/danielflores",
        github_url="github.com/danielflores",
        links=["danielflores.dev"],
        summary="Cybersecurity student focused on practical network analysis.",
        education=[
            Education(
                institution="North Carolina State University",
                degree="B.S.",
                program="Computer Science",
                end_date="May 2027",
                details=["Relevant coursework: Networks, Operating Systems"],
            )
        ],
        certifications=[Certification(name="CompTIA Security+", issuer="CompTIA")],
        skills=[
            Skill(name="Python", category="Programming"),
            Skill(name="Java", category="Programming"),
            Skill(name="Linux", category="Security"),
            Skill(name="Networking", category="Security"),
            Skill(name="Git", category="Tools"),
        ],
        projects=[
            Project(
                name="Packet Sniffer Project",
                description="Captured and analyzed network traffic.",
                bullets=[
                    "Built a Python packet sniffer using raw sockets.",
                    "Documented packet fields.",
                ],
                technologies=["Python", "Linux"],
            ),
            Project(
                name="Portfolio",
                bullets=["Built a portfolio site."],
                technologies=["HTML"],
            ),
        ],
        experience=[
            Experience(
                organization="Campus IT",
                title="IT Assistant",
                location="Raleigh, NC",
                start_date="August 2025",
                end_date="Present",
                bullets=["Supported students with Linux workstation issues."],
                technologies=["Linux"],
            )
        ],
    )


def _optimized() -> OptimizedResume:
    return FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(
        _request()
    ).optimized_resume


def test_render_basic_resume_to_markdown() -> None:
    rendered = MarkdownResumeRenderer().render(_resume())

    assert rendered.format == ResumeOutputFormat.MARKDOWN
    assert rendered.content.startswith("# Daniel Flores\n")
    assert "## Education" in rendered.content
    assert "## Projects" in rendered.content


def test_render_optimized_resume_to_markdown() -> None:
    rendered = MarkdownResumeRenderer().render(_optimized())

    assert rendered.target_job_title == "SOC Analyst Intern"
    assert rendered.target_company == "Example Security"
    assert "Packet Sniffer Project" in rendered.content


def test_contact_fields_render_only_when_present() -> None:
    resume = Resume(full_name="Daniel Flores", email="daniel@example.com")

    content = MarkdownResumeRenderer().render(resume).content

    assert "daniel@example.com" in content
    assert "LinkedIn" not in content
    assert "GitHub" not in content
    assert "None" not in content


def test_missing_contact_fields_are_omitted_with_warning() -> None:
    resume = Resume(full_name="Daniel Flores", summary="Student.")

    rendered = MarkdownResumeRenderer().render(resume)

    assert "contact information is missing" in rendered.warnings
    assert "|" not in rendered.content


def test_summary_renders_only_when_enabled() -> None:
    renderer = MarkdownResumeRenderer()

    included = renderer.render(_resume()).content
    omitted = renderer.render(
        _resume(),
        ResumeRenderOptions(include_summary=False),
    ).content

    assert "## Summary" in included
    assert "## Summary" not in omitted


def test_education_and_certifications_render_exact_facts() -> None:
    content = MarkdownResumeRenderer().render(_resume()).content

    assert "B.S., Computer Science - North Carolina State University" in content
    assert "May 2027" in content
    assert "- CompTIA Security+ - CompTIA" in content
    assert "GPA" not in content


def test_skills_render_grouped_when_categories_exist() -> None:
    content = MarkdownResumeRenderer().render(_resume()).content

    assert "Programming: Python, Java" in content
    assert "Security: Linux, Networking" in content
    assert "Tools: Git" in content


def test_skills_render_flat_without_categories() -> None:
    resume = Resume(
        full_name="Daniel Flores",
        skills=[Skill(name="Python"), Skill(name="Linux")],
    )

    content = MarkdownResumeRenderer().render(resume).content

    assert "Python, Linux" in content
    assert "Other:" not in content


def test_duplicate_skills_are_removed_using_normalized_names() -> None:
    resume = Resume(
        full_name="Daniel Flores",
        skills=[Skill(name="Python3"), Skill(name="Python 3"), Skill(name="python")],
    )

    content = MarkdownResumeRenderer().render(resume).content

    assert content.count("Python3") == 1
    assert "Python 3" not in content
    assert "python" not in content


def test_projects_and_experience_render_in_provided_order() -> None:
    content = MarkdownResumeRenderer().render(_resume()).content

    assert content.index("Packet Sniffer Project") < content.index("Portfolio")
    assert "IT Assistant - Campus IT" in content
    assert "Raleigh, NC | August 2025 - Present" in content


def test_renderer_does_not_rewrite_bullets_or_invent_technologies() -> None:
    content = MarkdownResumeRenderer().render(_resume()).content

    assert "- Built a Python packet sniffer using raw sockets." in content
    assert "Technologies: Python, Linux" in content
    assert "Splunk" not in content
    assert "SIEM" not in content


def test_project_bullet_limit_is_respected_and_warned() -> None:
    rendered = MarkdownResumeRenderer().render(
        _resume(),
        ResumeRenderOptions(max_bullets_per_project=1),
    )

    assert "Documented packet fields." not in rendered.content
    assert any("project Packet Sniffer Project" in warning for warning in rendered.warnings)


def test_experience_bullet_limit_is_respected_and_warned() -> None:
    resume = _resume().model_copy(
        update={
            "experience": [
                _resume().experience[0].model_copy(
                    update={"bullets": ["First exact bullet.", "Second exact bullet."]}
                )
            ]
        }
    )

    rendered = MarkdownResumeRenderer().render(
        resume,
        ResumeRenderOptions(max_bullets_per_experience=1),
    )

    assert "First exact bullet." in rendered.content
    assert "Second exact bullet." not in rendered.content
    assert any("experience IT Assistant" in warning for warning in rendered.warnings)


def test_additional_sections_render_generically() -> None:
    optimized = _optimized()
    optimized = optimized.model_copy(
        update={"additional_sections": {"Leadership": ["Led student security club."]}}
    )

    content = MarkdownResumeRenderer().render(optimized).content

    assert "## Leadership" in content
    assert "- Led student security club." in content


def test_strict_ats_format_forces_simple_headings_and_dash_bullets() -> None:
    options = ResumeRenderOptions(
        strict_ats_format=True,
        heading_style=HeadingStyle.ATS_SIMPLE,
        bullet_style=BulletStyle.ASTERISK,
    )

    content = MarkdownResumeRenderer().render(_resume(), options).content

    assert "#" not in content
    assert "*" not in content
    assert "EDUCATION" in content
    assert "- Built a Python packet sniffer using raw sockets." in content


def test_non_strict_mode_supports_asterisk_bullets() -> None:
    options = ResumeRenderOptions(
        strict_ats_format=False,
        bullet_style=BulletStyle.ASTERISK,
    )

    content = MarkdownResumeRenderer().render(_resume(), options).content

    assert "* Built a Python packet sniffer using raw sockets." in content


def test_metadata_comment_is_optional_and_limited() -> None:
    renderer = MarkdownResumeRenderer()

    without = renderer.render(_optimized()).content
    with_comment = renderer.render(
        _optimized(),
        ResumeRenderOptions(include_metadata_comment=True),
    ).content

    assert "<!--" not in without
    assert "Target Job: SOC Analyst Intern" in with_comment
    assert "Renderer Version:" in with_comment
    assert "optimization_plan" not in with_comment


def test_markdown_written_to_file_and_hash_generated(tmp_path: Path) -> None:
    result = MarkdownResumeRenderer().render_to_file(_resume(), tmp_path)
    path = Path(result.path)

    assert path.exists()
    assert path.read_text(encoding="utf-8") == result.rendered_resume.content
    assert result.byte_size == len(result.rendered_resume.content.encode("utf-8"))
    assert len(result.content_hash) == 64
    assert path.name == "daniel_flores_resume_resume.md"


def test_file_overwrite_protection_and_explicit_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "resume.md"
    renderer = MarkdownResumeRenderer()
    renderer.render_to_file(_resume(), path)

    with pytest.raises(ResumeOutputFileExistsError):
        renderer.render_to_file(_resume(), path)

    overwritten = renderer.render_to_file(_resume(), path, overwrite=True)
    assert Path(overwritten.path).exists()


def test_directory_output_avoids_duplicate_generated_names(tmp_path: Path) -> None:
    renderer = MarkdownResumeRenderer()
    first = renderer.render_to_file(_resume(), tmp_path)
    second = renderer.render_to_file(_resume(), tmp_path)

    assert Path(first.path).name == "daniel_flores_resume_resume.md"
    assert Path(second.path).name == "daniel_flores_resume_resume_2.md"


def test_filename_sanitization_and_generation() -> None:
    assert sanitize_filename("Daniel: Flores <> Resume?.MD") == "daniel_flores_resume.md"
    assert (
        generate_resume_filename("Daniel Flores", "SOC Analyst Intern", "CrowdStrike")
        == "daniel_flores_soc_analyst_intern_crowdstrike_resume.md"
    )


def test_unsupported_file_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedResumeFormatError):
        MarkdownResumeRenderer().render_to_file(_resume(), tmp_path / "resume.pdf")


def test_contact_only_resume_produces_empty_section_warning() -> None:
    rendered = MarkdownResumeRenderer().render(Resume(full_name="Daniel Flores"))

    assert "resume contains no renderable sections" in rendered.warnings


def test_custom_section_order_is_respected() -> None:
    options = ResumeRenderOptions(section_order=["Experience", "Education"])

    content = MarkdownResumeRenderer().render(_resume(), options).content

    assert content.index("## Experience") < content.index("## Education")


def test_unknown_section_order_entry_adds_warning() -> None:
    rendered = MarkdownResumeRenderer().render(
        _resume(),
        ResumeRenderOptions(section_order=["Imaginary", "Education"]),
    )

    assert "ignored unknown sections: Imaginary" in rendered.warnings


def test_source_identifiers_are_preserved_in_result_not_content() -> None:
    options = ResumeRenderOptions(source_resume_id="master-1", source_version_id="version-1")

    rendered = MarkdownResumeRenderer().render(_resume(), options)

    assert rendered.source_resume_id == "master-1"
    assert rendered.source_version_id == "version-1"
    assert "master-1" not in rendered.content
    assert "version-1" not in rendered.content


def test_original_resume_is_not_mutated() -> None:
    resume = _resume()
    before = resume.model_dump()

    MarkdownResumeRenderer().render(
        resume,
        ResumeRenderOptions(max_bullets_per_project=1),
    )

    assert resume.model_dump() == before


def test_same_input_and_options_produce_same_content() -> None:
    renderer = MarkdownResumeRenderer()
    options = ResumeRenderOptions(include_metadata_comment=True)

    first = renderer.render(_resume(), options)
    second = renderer.render(_resume(), options)

    assert first.content == second.content
    assert first.warnings == second.warnings
