"""Provider-neutral resume rendering with deterministic Markdown output."""

import hashlib
from collections import OrderedDict
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from ai_internship_assistant.domain.models import (
    BulletStyle,
    Certification,
    Education,
    Experience,
    HeadingStyle,
    OptimizedResume,
    OptimizedResumeContact,
    Project,
    RenderedResume,
    RenderedResumeFile,
    Resume,
    ResumeOutputFormat,
    ResumeRenderOptions,
    Skill,
)
from ai_internship_assistant.utils import canonical_skill_name
from ai_internship_assistant.utils.filenames import generate_resume_filename, sanitize_filename

_RENDERER_VERSION = "markdown-resume-renderer-v1"
_DEFAULT_SECTION_ORDER = [
    "Summary",
    "Education",
    "Certifications",
    "Skills",
    "Projects",
    "Experience",
    "Additional Sections",
]


class ResumeRenderingError(ValueError):
    """Base class for meaningful resume-rendering errors."""


class UnsupportedResumeFormatError(ResumeRenderingError):
    """Raised when a renderer is asked to produce an unsupported format."""


class ResumeOutputFileExistsError(ResumeRenderingError):
    """Raised when output would overwrite an existing file without permission."""


class ResumeOutputWriteError(ResumeRenderingError):
    """Raised when a rendered resume cannot be written safely."""


@runtime_checkable
class ResumeRenderer(Protocol):
    """Replaceable rendering interface for structured resume objects."""

    def render(
        self,
        resume: Resume | OptimizedResume,
        options: ResumeRenderOptions | None = None,
    ) -> RenderedResume:
        """Render a structured resume without altering its content."""


class MarkdownResumeRenderer:
    """Render source or optimized resumes as simple ATS-friendly Markdown."""

    def render(
        self,
        resume: Resume | OptimizedResume,
        options: ResumeRenderOptions | None = None,
    ) -> RenderedResume:
        """Render existing structured fields deterministically without rewriting."""

        resolved = options or ResumeRenderOptions()
        warnings: list[str] = []
        view = self._view(resume)
        blocks: list[str] = []
        if view["name"]:
            blocks.append(self._candidate_heading(str(view["name"]), resolved))
        else:
            warnings.append("candidate name is missing")
        if resolved.include_contact:
            contact = self._contact_line(view["contact"])
            if contact:
                blocks.append(contact)
            else:
                warnings.append("contact information is missing")

        renderers = self._section_renderers(view, resolved, warnings)
        rendered_section = False
        for section in self._section_order(resume, resolved, warnings):
            renderer = renderers.get(section.casefold())
            if renderer:
                rendered = renderer()
                if rendered:
                    blocks.append(rendered)
                    rendered_section = True
        if not rendered_section:
            warnings.append("resume contains no renderable sections")
        if resolved.include_metadata_comment:
            blocks.append(self._metadata_comment(view))
        return RenderedResume(
            content="\n\n".join(blocks).strip() + "\n",
            format=ResumeOutputFormat.MARKDOWN,
            candidate_name=str(view["name"]) if view["name"] else None,
            target_job_title=(
                str(view["target_job_title"]) if view["target_job_title"] else None
            ),
            target_company=str(view["target_company"]) if view["target_company"] else None,
            source_resume_id=resolved.source_resume_id,
            source_version_id=resolved.source_version_id,
            warnings=self._deduplicate(warnings),
            renderer_version=_RENDERER_VERSION,
        )

    def render_to_file(
        self,
        resume: Resume | OptimizedResume,
        output_path: Path,
        options: ResumeRenderOptions | None = None,
        *,
        overwrite: bool = False,
    ) -> RenderedResumeFile:
        """Render and write UTF-8 Markdown without silently overwriting files."""

        rendered = self.render(resume, options)
        requested_directory = output_path.exists() and output_path.is_dir()
        path = self._output_path(output_path, rendered)
        if path.exists() and not overwrite:
            if requested_directory:
                path = self._next_available_path(path)
            else:
                raise ResumeOutputFileExistsError("resume output file already exists")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered.content, encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ResumeOutputWriteError("resume output file could not be written") from exc
        content_bytes = rendered.content.encode("utf-8")
        return RenderedResumeFile(
            path=str(path),
            format=ResumeOutputFormat.MARKDOWN,
            byte_size=len(content_bytes),
            content_hash=hashlib.sha256(content_bytes).hexdigest(),
            rendered_resume=rendered,
        )

    def _view(self, resume: Resume | OptimizedResume) -> dict[str, object]:
        if isinstance(resume, OptimizedResume):
            return {
                "name": resume.contact.full_name,
                "contact": resume.contact,
                "summary": resume.summary,
                "education": resume.education,
                "certifications": resume.certifications,
                "skills": resume.skills,
                "projects": resume.projects,
                "experience": resume.experience,
                "additional": resume.additional_sections,
                "target_job_title": resume.target_job_title,
                "target_company": resume.target_company,
            }
        return {
            "name": resume.full_name,
            "contact": OptimizedResumeContact(
                source_file=resume.source_file,
                full_name=resume.full_name,
                email=resume.email,
                phone=resume.phone,
                location=resume.location,
                linkedin_url=resume.linkedin_url,
                github_url=resume.github_url,
                links=list(resume.links),
            ),
            "summary": resume.summary,
            "education": resume.education,
            "certifications": resume.certifications,
            "skills": resume.skills,
            "projects": resume.projects,
            "experience": resume.experience,
            "additional": {},
            "target_job_title": None,
            "target_company": None,
        }

    def _section_renderers(
        self,
        view: dict[str, object],
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> dict[str, Callable[[], str]]:
        return {
            "summary": lambda: self._summary(view["summary"], options),
            "education": lambda: self._education(view["education"], options),
            "certifications": lambda: self._certifications(
                view["certifications"],
                options,
            ),
            "skills": lambda: self._skills(view["skills"], options),
            "projects": lambda: self._projects(view["projects"], options, warnings),
            "experience": lambda: self._experience(view["experience"], options, warnings),
            "additional sections": lambda: self._additional(view["additional"], options),
            "additional": lambda: self._additional(view["additional"], options),
        }

    def _section_order(
        self,
        resume: Resume | OptimizedResume,
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> list[str]:
        source = options.section_order
        if source is None and isinstance(resume, OptimizedResume):
            source = resume.metadata.section_order
        order = list(source or _DEFAULT_SECTION_ORDER)
        known = {value.casefold() for value in _DEFAULT_SECTION_ORDER} | {
            "additional",
            "contact",
        }
        unknown = [value for value in order if value.casefold() not in known]
        if unknown:
            warnings.append(f"ignored unknown sections: {', '.join(unknown)}")
        included = {value.casefold() for value in order}
        order.extend(
            section for section in _DEFAULT_SECTION_ORDER if section.casefold() not in included
        )
        return order

    def _candidate_heading(self, name: str, options: ResumeRenderOptions) -> str:
        if options.heading_style == HeadingStyle.ATS_SIMPLE:
            return name
        return f"# {name}" if options.heading_style == HeadingStyle.MARKDOWN_H1 else f"## {name}"

    def _heading(self, title: str, options: ResumeRenderOptions, *, item: bool = False) -> str:
        if options.heading_style == HeadingStyle.ATS_SIMPLE:
            return title if item else title.upper()
        level = "###" if item else "##"
        if options.heading_style == HeadingStyle.MARKDOWN_H2:
            level = "####" if item else "###"
        return f"{level} {title}"

    def _contact_line(self, contact: object) -> str:
        if not isinstance(contact, OptimizedResumeContact):
            return ""
        return " | ".join(
            value
            for value in [
                contact.email,
                contact.phone,
                contact.linkedin_url,
                contact.github_url,
                *contact.links,
                contact.location,
            ]
            if value
        )

    def _summary(self, value: object, options: ResumeRenderOptions) -> str:
        if not options.include_summary or not isinstance(value, str) or not value.strip():
            return ""
        return f"{self._heading('Summary', options)}\n\n{value.strip()}"

    def _education(self, value: object, options: ResumeRenderOptions) -> str:
        if not options.include_education or not isinstance(value, list) or not value:
            return ""
        entries = [
            self._education_entry(item, options)
            for item in value
            if isinstance(item, Education)
        ]
        return self._section("Education", entries, options)

    def _education_entry(self, item: Education, options: ResumeRenderOptions) -> str:
        qualification = ", ".join(value for value in [item.degree, item.program] if value)
        first = " - ".join(value for value in [qualification, item.institution] if value)
        dates = self._dates(item.start_date, item.end_date)
        lines = [first, dates, *(self._bullet(detail, options) for detail in item.details)]
        return "\n".join(value for value in lines if value)

    def _certifications(self, value: object, options: ResumeRenderOptions) -> str:
        if not options.include_certifications or not isinstance(value, list) or not value:
            return ""
        entries = [
            self._bullet(self._certification_text(item), options)
            for item in value
            if isinstance(item, Certification)
        ]
        return self._section("Certifications", entries, options)

    def _certification_text(self, item: Certification) -> str:
        text = " - ".join(value for value in [item.name, item.issuer] if value)
        dates = self._dates(item.issued_date, item.expiration_date)
        return f"{text} ({dates})" if dates else text

    def _skills(self, value: object, options: ResumeRenderOptions) -> str:
        if not options.include_skills or not isinstance(value, list) or not value:
            return ""
        skills = self._deduplicate_skills(item for item in value if isinstance(item, Skill))
        if not skills:
            return ""
        categorized = any(skill.category for skill in skills)
        if categorized:
            groups: OrderedDict[str, list[str]] = OrderedDict()
            for skill in skills:
                category = skill.category or "Other"
                groups.setdefault(category, []).append(skill.name)
            entries = [f"{category}: {', '.join(names)}" for category, names in groups.items()]
        else:
            entries = [", ".join(skill.name for skill in skills)]
        return self._section("Skills", entries, options)

    def _projects(
        self,
        value: object,
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> str:
        if not options.include_projects or not isinstance(value, list) or not value:
            return ""
        entries = [
            self._project_entry(item, options, warnings)
            for item in value
            if isinstance(item, Project)
        ]
        return self._section("Projects", entries, options)

    def _project_entry(
        self,
        item: Project,
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> str:
        bullets = self._limited_bullets(
            item.bullets,
            options.max_bullets_per_project,
            f"project {item.name}",
            warnings,
        )
        lines = [
            self._heading(item.name, options, item=True),
            item.description or "",
            *(self._bullet(bullet, options) for bullet in bullets),
        ]
        if item.technologies:
            lines.append(f"Technologies: {', '.join(item.technologies)}")
        if item.links:
            lines.append(f"Links: {', '.join(item.links)}")
        return "\n\n".join(value for value in lines if value)

    def _experience(
        self,
        value: object,
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> str:
        if not options.include_experience or not isinstance(value, list) or not value:
            return ""
        entries = [
            self._experience_entry(item, options, warnings)
            for item in value
            if isinstance(item, Experience)
        ]
        return self._section("Experience", entries, options)

    def _experience_entry(
        self,
        item: Experience,
        options: ResumeRenderOptions,
        warnings: list[str],
    ) -> str:
        bullets = self._limited_bullets(
            item.bullets,
            options.max_bullets_per_experience,
            f"experience {item.title} at {item.organization}",
            warnings,
        )
        details = " | ".join(
            value for value in [item.location, self._dates(item.start_date, item.end_date)] if value
        )
        lines = [
            self._heading(f"{item.title} - {item.organization}", options, item=True),
            details,
            *(self._bullet(bullet, options) for bullet in bullets),
        ]
        if item.technologies:
            lines.append(f"Technologies: {', '.join(item.technologies)}")
        return "\n\n".join(value for value in lines if value)

    def _additional(self, value: object, options: ResumeRenderOptions) -> str:
        if not options.include_additional_sections or not isinstance(value, dict):
            return ""
        sections = []
        for title, entries in value.items():
            if isinstance(title, str) and isinstance(entries, list) and entries:
                sections.append(
                    "\n".join(
                        [
                            self._heading(title, options),
                            "",
                            *(self._bullet(str(entry), options) for entry in entries),
                        ]
                    ).strip()
                )
        return "\n\n".join(sections)

    def _section(
        self,
        title: str,
        entries: Sequence[str],
        options: ResumeRenderOptions,
    ) -> str:
        populated = [entry for entry in entries if entry]
        if not populated:
            return ""
        return f"{self._heading(title, options)}\n\n" + "\n\n".join(populated)

    def _limited_bullets(
        self,
        bullets: Sequence[str],
        limit: int | None,
        label: str,
        warnings: list[str],
    ) -> list[str]:
        if limit is None or len(bullets) <= limit:
            return list(bullets)
        warnings.append(f"trimmed {len(bullets) - limit} bullet(s) from {label}")
        return list(bullets[:limit])

    def _bullet(self, value: str, options: ResumeRenderOptions) -> str:
        marker = (
            "-"
            if options.strict_ats_format or options.bullet_style == BulletStyle.DASH
            else "*"
        )
        return f"{marker} {value}"

    def _dates(self, start: str | None, end: str | None) -> str:
        return " - ".join(value for value in [start, end] if value)

    def _metadata_comment(self, view: dict[str, object]) -> str:
        lines = [
            "<!--",
            "Generated by AI Internship Application Assistant",
        ]
        if view["target_job_title"]:
            lines.append(f"Target Job: {view['target_job_title']}")
        if view["target_company"]:
            lines.append(f"Target Company: {view['target_company']}")
        lines.extend([f"Renderer Version: {_RENDERER_VERSION}", "-->"])
        return "\n".join(lines)

    def _output_path(self, requested: Path, rendered: RenderedResume) -> Path:
        if requested.exists() and requested.is_dir():
            return requested / generate_resume_filename(
                rendered.candidate_name,
                rendered.target_job_title,
                rendered.target_company,
            )
        suffix = requested.suffix.casefold()
        if suffix and suffix != ".md":
            raise UnsupportedResumeFormatError("Markdown renderer only supports .md output")
        name = sanitize_filename(requested.name or "resume.md")
        if not Path(name).suffix:
            name += ".md"
        return requested.parent / name

    def _deduplicate_skills(self, skills: Iterable[Skill]) -> list[Skill]:
        result: list[Skill] = []
        seen: set[str] = set()
        for skill in skills:
            canonical = canonical_skill_name(skill.name)
            if canonical not in seen:
                seen.add(canonical)
                result.append(skill)
        return result

    def _next_available_path(self, path: Path) -> Path:
        version = 2
        while True:
            candidate = path.with_name(f"{path.stem}_{version}{path.suffix}")
            if not candidate.exists():
                return candidate
            version += 1

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            if value not in seen:
                seen.add(value)
                result.append(value)
        return result
