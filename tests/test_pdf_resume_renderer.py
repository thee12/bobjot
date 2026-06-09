"""Tests for selectable-text ATS-friendly PDF resume export."""

from pathlib import Path

import pdfplumber
import pytest

from ai_internship_assistant.domain.models import (
    OptimizedResume,
    PdfRenderOptions,
    Resume,
    ResumeOutputFormat,
)
from ai_internship_assistant.services import (
    PdfResumeRenderer,
    ResumeOutputFileExistsError,
    UnsupportedResumeFormatError,
)
from tests.test_resume_renderer import _optimized, _resume


def _pdf_text(path: Path) -> str:
    with pdfplumber.open(path) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def _export(
    tmp_path: Path,
    resume: Resume | OptimizedResume | None = None,
    options: PdfRenderOptions | None = None,
) -> tuple[Path, str]:
    result = PdfResumeRenderer().render_to_file(resume or _resume(), tmp_path, options)
    path = Path(result.path)
    return path, _pdf_text(path)


def test_export_basic_resume_to_pdf(tmp_path: Path) -> None:
    path, text = _export(tmp_path)

    assert path.exists()
    assert path.suffix == ".pdf"
    assert "Daniel Flores" in text


def test_export_optimized_resume_to_pdf(tmp_path: Path) -> None:
    path, text = _export(tmp_path, _optimized())

    assert path.name == "alex_candidate_soc_analyst_intern_example_security_resume.pdf"
    assert "Packet Sniffer Project" in text


def test_candidate_contact_and_sections_are_extractable(tmp_path: Path) -> None:
    _, text = _export(tmp_path)

    assert "daniel@example.com" in text
    assert "linkedin.com/in/danielflores" in text
    assert "EDUCATION" in text
    assert "CERTIFICATIONS" in text
    assert "SKILLS" in text
    assert "PROJECTS" in text
    assert "EXPERIENCE" in text


def test_contact_fields_render_only_when_present(tmp_path: Path) -> None:
    resume = Resume(full_name="Daniel Flores", email="daniel@example.com")

    _, text = _export(tmp_path, resume)

    assert "daniel@example.com" in text
    assert "None" not in text
    assert "LinkedIn" not in text


def test_education_certifications_and_skills_render(tmp_path: Path) -> None:
    _, text = _export(tmp_path)

    assert "B.S., Computer Science - North Carolina State University" in text
    assert "CompTIA Security+ - CompTIA" in text
    assert "Programming: Python, Java" in text
    assert "Security: Linux, Networking" in text


def test_projects_experience_bullets_and_technologies_render(tmp_path: Path) -> None:
    _, text = _export(tmp_path)

    assert "Packet Sniffer Project" in text
    assert "Technologies: Python, Linux" in text
    assert "Built a Python packet sniffer using raw sockets." in text
    assert "IT Assistant - Campus IT" in text


def test_additional_sections_render_generically(tmp_path: Path) -> None:
    optimized = _optimized().model_copy(
        update={"additional_sections": {"Leadership": ["Led student security club."]}}
    )

    _, text = _export(tmp_path, optimized)

    assert "LEADERSHIP" in text
    assert "Led student security club." in text


def test_missing_sections_are_omitted_gracefully(tmp_path: Path) -> None:
    resume = Resume(full_name="Daniel Flores", email="daniel@example.com")

    _, text = _export(tmp_path, resume)

    assert "EDUCATION" not in text
    assert "PROJECTS" not in text


def test_exporter_does_not_add_unsafe_content_or_rewrite_bullets(tmp_path: Path) -> None:
    _, text = _export(tmp_path)

    assert "Built a Python packet sniffer using raw sockets." in text
    assert "Splunk" not in text
    assert "SIEM" not in text
    assert "40%" not in text


def test_max_bullets_and_entries_are_respected(tmp_path: Path) -> None:
    options = PdfRenderOptions(
        max_projects=1,
        max_experiences=0,
        max_bullets_per_project=1,
    )
    result = PdfResumeRenderer().render_to_file(_resume(), tmp_path, options)
    text = _pdf_text(Path(result.path))

    assert "Packet Sniffer Project" in text
    assert "Portfolio" not in text
    assert "Documented packet fields." not in text
    assert "EXPERIENCE" not in text
    assert any("trimmed" in warning for warning in result.rendered_resume.warnings)


def test_summary_visibility_is_configurable(tmp_path: Path) -> None:
    _, included = _export(tmp_path / "included", options=PdfRenderOptions(include_summary=True))
    _, omitted = _export(tmp_path / "omitted", options=PdfRenderOptions(include_summary=False))

    assert "SUMMARY" in included
    assert "SUMMARY" not in omitted


def test_parent_directory_is_created_and_filename_is_sanitized(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "Daniel: Resume?.PDF"

    result = PdfResumeRenderer().render_to_file(_resume(), output)

    assert Path(result.path).exists()
    assert Path(result.path).name == "daniel_resume.pdf"


def test_overwrite_protection_and_allow_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "resume.pdf"
    renderer = PdfResumeRenderer()
    renderer.render_to_file(_resume(), output)

    with pytest.raises(ResumeOutputFileExistsError):
        renderer.render_to_file(_resume(), output)

    result = renderer.render_to_file(
        _resume(),
        output,
        PdfRenderOptions(allow_overwrite=True),
    )
    assert Path(result.path).exists()


def test_directory_output_avoids_duplicate_names(tmp_path: Path) -> None:
    renderer = PdfResumeRenderer()
    first = renderer.render_to_file(_resume(), tmp_path)
    second = renderer.render_to_file(_resume(), tmp_path)

    assert Path(first.path).name == "daniel_flores_resume_resume.pdf"
    assert Path(second.path).name == "daniel_flores_resume_resume_2.pdf"


def test_rendered_file_metadata_and_page_count_are_returned(tmp_path: Path) -> None:
    result = PdfResumeRenderer().render_to_file(_resume(), tmp_path)

    assert result.format == ResumeOutputFormat.PDF
    assert result.byte_size > 0
    assert len(result.content_hash) == 64
    assert result.page_count
    assert result.rendered_resume.format == ResumeOutputFormat.PDF
    assert result.rendered_resume.renderer_version == "pdf-resume-renderer-v1"


def test_pdf_contains_selectable_text_and_no_images(tmp_path: Path) -> None:
    path, _ = _export(tmp_path)

    with pdfplumber.open(path) as pdf:
        assert pdf.pages[0].extract_text()
        assert all(page.images == [] for page in pdf.pages)


def test_strict_ats_output_uses_single_column_plain_text(tmp_path: Path) -> None:
    path, text = _export(tmp_path, options=PdfRenderOptions(strict_ats_format=True))

    with pdfplumber.open(path) as pdf:
        assert all(page.images == [] for page in pdf.pages)
        assert all(page.curves == [] for page in pdf.pages)
    assert "EDUCATION" in text
    assert "github.com/danielflores" in text


def test_compact_mode_changes_pdf_layout_bytes(tmp_path: Path) -> None:
    compact = PdfResumeRenderer().render_to_file(
        _resume(),
        tmp_path / "compact.pdf",
        PdfRenderOptions(compact_mode=True),
    )
    relaxed = PdfResumeRenderer().render_to_file(
        _resume(),
        tmp_path / "relaxed.pdf",
        PdfRenderOptions(compact_mode=False),
    )

    assert compact.content_hash != relaxed.content_hash


def test_pdf_metadata_is_set_safely(tmp_path: Path) -> None:
    path, _ = _export(tmp_path, _optimized())

    with pdfplumber.open(path) as pdf:
        metadata = pdf.metadata

    assert metadata["Title"] == "Alex Candidate - Resume - SOC Analyst Intern"
    assert metadata["Author"] == "Alex Candidate"
    assert metadata["Creator"] == "AI Internship Application Assistant"
    assert "optimization" not in str(metadata).casefold()
    assert "safety" not in str(metadata).casefold()


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedResumeFormatError):
        PdfResumeRenderer().render_to_file(_resume(), tmp_path / "resume.docx")


def test_original_resume_is_not_mutated(tmp_path: Path) -> None:
    resume = _resume()
    before = resume.model_dump()

    PdfResumeRenderer().render_to_file(
        resume,
        tmp_path,
        PdfRenderOptions(max_projects=1, max_bullets_per_project=1),
    )

    assert resume.model_dump() == before


def test_render_returns_visible_text_without_writing_file() -> None:
    rendered = PdfResumeRenderer().render(_resume())

    assert rendered.format == ResumeOutputFormat.PDF
    assert "Daniel Flores" in rendered.content
    assert "Packet Sniffer Project" in rendered.content


def test_source_ids_are_preserved_in_metadata_not_pdf(tmp_path: Path) -> None:
    options = PdfRenderOptions(source_resume_id="master-1", source_version_id="version-1")

    result = PdfResumeRenderer().render_to_file(_resume(), tmp_path, options)
    text = _pdf_text(Path(result.path))

    assert result.rendered_resume.source_resume_id == "master-1"
    assert result.rendered_resume.source_version_id == "version-1"
    assert "master-1" not in text
    assert "version-1" not in text


def test_custom_section_order_is_respected(tmp_path: Path) -> None:
    options = PdfRenderOptions(section_order=["Experience", "Education"])

    _, text = _export(tmp_path, options=options)

    assert text.index("EXPERIENCE") < text.index("EDUCATION")


def test_missing_name_and_empty_sections_produce_warnings() -> None:
    rendered = PdfResumeRenderer().render(Resume(email="daniel@example.com"))

    assert "candidate name is missing" in rendered.warnings
    assert "resume contains no renderable sections" in rendered.warnings


def test_text_validation_can_be_disabled(tmp_path: Path) -> None:
    result = PdfResumeRenderer().render_to_file(
        _resume(),
        tmp_path,
        PdfRenderOptions(validate_extractable_text=False),
    )

    assert result.page_count
    assert not any("could not extract" in warning for warning in result.rendered_resume.warnings)


def test_deterministic_pdf_bytes_for_same_input(tmp_path: Path) -> None:
    renderer = PdfResumeRenderer()
    first = renderer.render_to_file(_resume(), tmp_path / "first.pdf")
    second = renderer.render_to_file(_resume(), tmp_path / "second.pdf")

    assert first.content_hash == second.content_hash


def test_pdf_page_size_option_is_supported(tmp_path: Path) -> None:
    result = PdfResumeRenderer().render_to_file(
        _resume(),
        tmp_path,
        PdfRenderOptions(page_size="A4"),
    )

    with pdfplumber.open(result.path) as pdf:
        assert pdf.pages[0].height == pytest.approx(841.89, abs=1)
