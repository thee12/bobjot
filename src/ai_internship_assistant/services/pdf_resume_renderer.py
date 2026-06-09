"""Selectable-text, single-column ATS-friendly PDF resume rendering."""

import hashlib
from collections.abc import Iterable
from html import escape
from pathlib import Path

import pdfplumber
from reportlab.lib.enums import TA_CENTER, TA_LEFT  # type: ignore[import-untyped]
from reportlab.lib.pagesizes import A4, letter  # type: ignore[import-untyped]
from reportlab.lib.styles import ParagraphStyle  # type: ignore[import-untyped]
from reportlab.lib.units import inch  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]
from reportlab.platypus import (  # type: ignore[import-untyped]
    Flowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)
from reportlab.platypus.doctemplate import LayoutError  # type: ignore[import-untyped]

from ai_internship_assistant.domain.models import (
    HeadingStyle,
    OptimizedResume,
    PdfRenderOptions,
    RenderedResume,
    RenderedResumeFile,
    Resume,
    ResumeOutputFormat,
    ResumeRenderOptions,
)
from ai_internship_assistant.services.resume_generator import (
    MarkdownResumeRenderer,
    ResumeOutputFileExistsError,
    ResumeOutputWriteError,
    ResumeRenderingError,
    UnsupportedResumeFormatError,
)
from ai_internship_assistant.utils.filenames import generate_resume_filename, sanitize_filename

_RENDERER_VERSION = "pdf-resume-renderer-v1"


class _InvariantCanvas(canvas.Canvas):  # type: ignore[misc]
    """Create reproducible PDF metadata and trailer identifiers."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["invariant"] = 1
        super().__init__(*args, **kwargs)


class PdfRenderingError(ResumeRenderingError):
    """Raised when ReportLab cannot produce or validate a resume PDF."""


class PdfResumeRenderer:
    """Render structured resumes as selectable-text ATS-friendly PDF files."""

    def render(
        self,
        resume: Resume | OptimizedResume,
        options: ResumeRenderOptions | None = None,
    ) -> RenderedResume:
        """Return the deterministic visible-text representation used for PDF output."""

        self._validate_resume(resume)
        resolved = self._options(options)
        prepared, length_warnings = self._prepare_resume(resume, resolved)
        rendered = MarkdownResumeRenderer().render(prepared, self._markdown_options(resolved))
        return RenderedResume(
            content=rendered.content,
            format=ResumeOutputFormat.PDF,
            candidate_name=rendered.candidate_name,
            target_job_title=rendered.target_job_title,
            target_company=rendered.target_company,
            source_resume_id=resolved.source_resume_id,
            source_version_id=resolved.source_version_id,
            warnings=self._deduplicate([*rendered.warnings, *length_warnings]),
            renderer_version=_RENDERER_VERSION,
        )

    def render_to_file(
        self,
        resume: Resume | OptimizedResume,
        output_path: Path,
        options: ResumeRenderOptions | None = None,
        *,
        overwrite: bool | None = None,
    ) -> RenderedResumeFile:
        """Write one text-based PDF and return artifact and page metadata."""

        resolved = self._options(options)
        rendered = self.render(resume, resolved)
        requested_directory = output_path.exists() and output_path.is_dir()
        path = self._output_path(output_path, rendered)
        allow_overwrite = resolved.allow_overwrite if overwrite is None else overwrite
        if path.exists() and not allow_overwrite:
            if requested_directory:
                path = self._next_available_path(path)
            else:
                raise ResumeOutputFileExistsError("resume output file already exists")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._write_pdf(path, rendered, resolved)
            content = path.read_bytes()
        except (OSError, ValueError, LayoutError) as exc:
            raise ResumeOutputWriteError("PDF resume output file could not be written") from exc
        page_count, validation_warnings = self._validate_pdf(path, rendered, resolved)
        warnings = list(rendered.warnings)
        if page_count > 1:
            warnings.append(f"PDF contains {page_count} pages; review length before applying")
        warnings.extend(validation_warnings)
        rendered = rendered.model_copy(update={"warnings": self._deduplicate(warnings)})
        return RenderedResumeFile(
            path=str(path),
            format=ResumeOutputFormat.PDF,
            byte_size=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
            rendered_resume=rendered,
            page_count=page_count,
        )

    def _write_pdf(
        self,
        path: Path,
        rendered: RenderedResume,
        options: PdfRenderOptions,
    ) -> None:
        page_size = letter if options.page_size == "Letter" else A4
        document = SimpleDocTemplate(
            str(path),
            pagesize=page_size,
            leftMargin=options.margin_left * inch,
            rightMargin=options.margin_right * inch,
            topMargin=options.margin_top * inch,
            bottomMargin=options.margin_bottom * inch,
            title=self._title(rendered),
            author=rendered.candidate_name or "",
            subject="ATS-friendly resume",
            creator="AI Internship Application Assistant",
        )
        styles = self._styles(options)
        story: list[Flowable] = []
        lines = rendered.content.splitlines()
        for index, line in enumerate(lines):
            text = line.strip()
            if not text:
                if story and not options.compact_mode:
                    story.append(Spacer(1, 2))
                continue
            if index == 0 and rendered.candidate_name:
                story.append(Paragraph(escape(text), styles["name"]))
            elif self._is_section_heading(text):
                story.append(Paragraph(escape(text), styles["heading"]))
            elif text.startswith("- "):
                story.append(
                    Paragraph(
                        escape(text[2:]),
                        styles["bullet"],
                        bulletText="-",
                    )
                )
            elif " | " in text and index <= 2:
                story.append(Paragraph(escape(text), styles["contact"]))
            else:
                story.append(Paragraph(escape(text), styles["body"]))

        def set_metadata(pdf_canvas: canvas.Canvas, _: object) -> None:
            pdf_canvas.setTitle(self._title(rendered))
            pdf_canvas.setAuthor(rendered.candidate_name or "")
            pdf_canvas.setSubject("ATS-friendly resume")
            pdf_canvas.setCreator("AI Internship Application Assistant")
            pdf_canvas.setKeywords("resume, ATS")

        document.build(
            story,
            onFirstPage=set_metadata,
            onLaterPages=set_metadata,
            canvasmaker=_InvariantCanvas,
        )

    def _styles(self, options: PdfRenderOptions) -> dict[str, ParagraphStyle]:
        body_after = 1 if options.compact_mode else 4
        heading_before = 4 if options.compact_mode else 8
        leading = options.font_size * options.line_spacing
        return {
            "name": ParagraphStyle(
                "ResumeName",
                fontName=self._bold_font(options.font_name),
                fontSize=options.name_font_size,
                leading=options.name_font_size * 1.1,
                alignment=TA_CENTER,
                spaceAfter=2 if options.compact_mode else 5,
            ),
            "contact": ParagraphStyle(
                "ResumeContact",
                fontName=options.font_name,
                fontSize=options.font_size,
                leading=leading,
                alignment=TA_CENTER,
                spaceAfter=3 if options.compact_mode else 7,
            ),
            "heading": ParagraphStyle(
                "ResumeHeading",
                fontName=self._bold_font(options.font_name),
                fontSize=options.heading_font_size,
                leading=options.heading_font_size * 1.05,
                alignment=TA_LEFT,
                spaceBefore=heading_before,
                spaceAfter=2,
                keepWithNext=True,
            ),
            "body": ParagraphStyle(
                "ResumeBody",
                fontName=options.font_name,
                fontSize=options.font_size,
                leading=leading,
                alignment=TA_LEFT,
                spaceAfter=body_after,
            ),
            "bullet": ParagraphStyle(
                "ResumeBullet",
                fontName=options.font_name,
                fontSize=options.font_size,
                leading=leading,
                alignment=TA_LEFT,
                leftIndent=options.bullet_indent * inch,
                firstLineIndent=-0.12 * inch,
                bulletIndent=0.08 * inch,
                spaceAfter=body_after,
            ),
        }

    def _prepare_resume(
        self,
        resume: Resume | OptimizedResume,
        options: PdfRenderOptions,
    ) -> tuple[Resume | OptimizedResume, list[str]]:
        projects = list(resume.projects)
        experience = list(resume.experience)
        warnings: list[str] = []
        if options.max_projects is not None and len(projects) > options.max_projects:
            warnings.append(f"trimmed {len(projects) - options.max_projects} project entry(s)")
            projects = projects[: options.max_projects]
        if options.max_experiences is not None and len(experience) > options.max_experiences:
            warnings.append(
                f"trimmed {len(experience) - options.max_experiences} experience entry(s)"
            )
            experience = experience[: options.max_experiences]
        return (
            resume.model_copy(
                update={"projects": projects, "experience": experience},
                deep=True,
            ),
            warnings,
        )

    def _markdown_options(self, options: PdfRenderOptions) -> ResumeRenderOptions:
        shared = {
            name: getattr(options, name)
            for name in ResumeRenderOptions.model_fields
        }
        shared["heading_style"] = HeadingStyle.ATS_SIMPLE
        shared["strict_ats_format"] = True
        return ResumeRenderOptions.model_validate(shared)

    def _validate_pdf(
        self,
        path: Path,
        rendered: RenderedResume,
        options: PdfRenderOptions,
    ) -> tuple[int, list[str]]:
        try:
            with pdfplumber.open(path) as pdf:
                page_count = len(pdf.pages)
                if not options.validate_extractable_text:
                    return page_count, []
                extracted = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except (OSError, ValueError) as exc:
            raise PdfRenderingError("generated PDF could not be validated") from exc
        extracted_normalized = " ".join(extracted.split())
        representative_bullet = next(
            (
                line.removeprefix("- ").strip()
                for line in rendered.content.splitlines()
                if line.startswith("- ")
            ),
            None,
        )
        required = [
            value
            for value in [
                rendered.candidate_name,
                *(
                    heading
                    for heading in ["EDUCATION", "SKILLS", "PROJECTS", "EXPERIENCE"]
                    if heading in rendered.content
                ),
                representative_bullet,
            ]
            if value
        ]
        missing = [
            value
            for value in required
            if " ".join(value.split()) not in extracted_normalized
        ]
        warnings = (
            [f"PDF text validation could not extract: {', '.join(missing)}"]
            if missing
            else []
        )
        return page_count, warnings

    def _options(self, options: ResumeRenderOptions | None) -> PdfRenderOptions:
        if options is None:
            return PdfRenderOptions()
        if isinstance(options, PdfRenderOptions):
            return options
        shared = {
            name: getattr(options, name)
            for name in ResumeRenderOptions.model_fields
        }
        return PdfRenderOptions.model_validate(shared)

    def _output_path(self, requested: Path, rendered: RenderedResume) -> Path:
        if requested.exists() and requested.is_dir():
            return requested / generate_resume_filename(
                rendered.candidate_name,
                rendered.target_job_title,
                rendered.target_company,
                extension=".pdf",
            )
        suffix = requested.suffix.casefold()
        if suffix and suffix != ".pdf":
            raise UnsupportedResumeFormatError("PDF renderer only supports .pdf output")
        name = sanitize_filename(requested.name or "resume.pdf")
        if not Path(name).suffix:
            name += ".pdf"
        return requested.parent / name

    def _next_available_path(self, path: Path) -> Path:
        version = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{version}{path.suffix}")
            if not candidate.exists():
                return candidate
            version += 1

    def _title(self, rendered: RenderedResume) -> str:
        values = [
            rendered.candidate_name or "Candidate",
            "Resume",
            *(value for value in [rendered.target_job_title] if value),
        ]
        return " - ".join(values)

    def _is_section_heading(self, value: str) -> bool:
        return value.isupper() and len(value) <= 80

    def _bold_font(self, font_name: str) -> str:
        return "Times-Bold" if font_name == "Times-Roman" else f"{font_name}-Bold"

    def _validate_resume(self, resume: object) -> None:
        if not isinstance(resume, (Resume, OptimizedResume)):
            raise ResumeRenderingError("resume must be a Resume or OptimizedResume")

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
