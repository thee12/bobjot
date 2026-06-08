"""Resume validation engine.

The validator inspects parsed Resume objects for completeness, consistency,
and data quality. It reports issues in a separate ValidationReport and never
repairs, rewrites, optimizes, scores, or mutates the original Resume.

Future modules can consume the Resume and ValidationReport independently. The
checks here are intentionally provider-agnostic and are not coupled to OpenAI
or any specific LLM implementation.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel

from ai_internship_assistant.domain.models import (
    Resume,
    ValidationCategory,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from ai_internship_assistant.utils import normalize_skill_name

_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_YEAR_PATTERN = re.compile(r"\b(?P<year>\d{4})\b")
_PHONE_PATTERN = re.compile(r"(?=(?:.*\d){7,})^[+()\-\.\s\d]+$")
_LARGE_SECTION_WORD_LIMIT = 3_000


class ResumeValidationError(TypeError):
    """Raised when the validator is called with a programmer-error input."""


class ResumeValidator:
    """Validate parsed Resume objects without modifying them.

    The validator is forgiving: missing optional items such as GitHub,
    LinkedIn, certifications, or work experience are informational rather than
    fatal. Errors are reserved for cases that make downstream use unreliable,
    such as a completely empty parsed resume.
    """

    def validate(self, resume: Resume) -> ValidationReport:
        """Return a ValidationReport for a parsed Resume object."""

        if resume is None:
            msg = "resume must not be None"
            raise ResumeValidationError(msg)
        if not isinstance(resume, Resume):
            msg = f"resume must be a Resume instance, got {type(resume).__name__}"
            raise ResumeValidationError(msg)

        issues: list[ValidationIssue] = []
        issues.extend(self._validate_contact(resume))
        issues.extend(self._validate_skills(resume))
        issues.extend(self._validate_education(resume))
        issues.extend(self._validate_projects(resume))
        issues.extend(self._validate_experience(resume))
        issues.extend(self._validate_certifications(resume))
        issues.extend(self._validate_general_consistency(resume))
        return ValidationReport(issues=issues)

    def _validate_contact(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if self._is_blank(self._get(resume, "full_name")):
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    "Resume is missing a candidate name.",
                    "full_name",
                    "Confirm whether the source resume includes a name.",
                )
            )

        email = self._get(resume, "email")
        if self._is_blank(email):
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    "Resume is missing an email address.",
                    "email",
                    "Confirm whether the source resume includes an email address.",
                )
            )
        elif isinstance(email, str) and _EMAIL_PATTERN.fullmatch(email) is None:
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    "Resume email appears malformed.",
                    "email",
                    "Review the parsed email against the source resume.",
                )
            )

        phone = self._get(resume, "phone")
        if self._is_blank(phone):
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    "Resume is missing a phone number.",
                    "phone",
                    "Confirm whether the source resume includes a phone number.",
                )
            )
        elif isinstance(phone, str) and _PHONE_PATTERN.fullmatch(phone) is None:
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    "Resume phone number appears malformed.",
                    "phone",
                    "Review the parsed phone number against the source resume.",
                )
            )

        issues.extend(
            self._validate_optional_profile_url(
                resume=resume,
                field_name="linkedin_url",
                label="LinkedIn",
                expected_host="linkedin.com",
            )
        )
        issues.extend(
            self._validate_optional_profile_url(
                resume=resume,
                field_name="github_url",
                label="GitHub",
                expected_host="github.com",
            )
        )

        return issues

    def _validate_skills(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        skills = self._as_sequence(self._get(resume, "skills"))

        if not skills:
            return [
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.SKILL,
                    "Resume does not include any detected technical skills.",
                    "skills",
                    "Confirm whether the source resume includes a skills section.",
                )
            ]

        normalized_skill_names: list[str] = []
        capitalization_groups: dict[str, set[str]] = {}
        for index, skill in enumerate(skills):
            name = self._get(skill, "name")
            if self._is_blank(name):
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.SKILL,
                        "Skill entry is missing a name.",
                        f"skills[{index}].name",
                        "Review the parsed skills list.",
                    )
                )
                continue

            assert isinstance(name, str)
            normalized_name = normalize_skill_name(name)
            normalized_skill_names.append(normalized_name)
            capitalization_groups.setdefault(normalized_name, set()).add(name)

        issues.extend(
            self._duplicate_issues(
                normalized_skill_names,
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.SKILL,
                field_name="skills",
                label="skill",
            )
        )

        for normalized_name, variants in sorted(capitalization_groups.items()):
            if len({variant.casefold() for variant in variants}) == 1 and len(variants) <= 1:
                continue
            if len(variants) > 1:
                issues.append(
                    self._issue(
                        ValidationSeverity.INFO,
                        ValidationCategory.SKILL,
                        f"Skill capitalization is inconsistent for {normalized_name}.",
                        "skills",
                        "Keep capitalization consistent in future generated outputs.",
                    )
                )

        technology_names = self._collect_technologies(resume)
        issues.extend(
            self._duplicate_issues(
                technology_names,
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.SKILL,
                field_name="technologies",
                label="technology",
            )
        )

        return issues

    def _validate_education(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        education_entries = self._as_sequence(self._get(resume, "education"))

        if not education_entries:
            return [
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.EDUCATION,
                    "Resume does not include an education section.",
                    "education",
                    "Confirm whether the source resume includes education.",
                )
            ]

        for index, education in enumerate(education_entries):
            if self._is_blank(self._get(education, "institution")):
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.EDUCATION,
                        "Education entry is missing a school name.",
                        f"education[{index}].institution",
                        "Review the parsed education section.",
                    )
                )
            if self._is_blank(self._get(education, "degree")):
                issues.append(
                    self._issue(
                        ValidationSeverity.INFO,
                        ValidationCategory.EDUCATION,
                        "Education entry is missing a degree.",
                        f"education[{index}].degree",
                        "Leave missing if the source resume does not list a degree.",
                    )
                )
            issues.extend(self._validate_education_years(education, index))

        return issues

    def _validate_projects(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        projects = self._as_sequence(self._get(resume, "projects"))
        project_names: list[str] = []

        for index, project in enumerate(projects):
            name = self._get(project, "name")
            if self._is_blank(name):
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.PROJECT,
                        "Project entry is missing a title.",
                        f"projects[{index}].name",
                        "Review the parsed projects section.",
                    )
                )
            elif isinstance(name, str):
                project_names.append(name.casefold())

            description = self._get(project, "description")
            bullets = self._as_sequence(self._get(project, "bullets"))
            if self._is_blank(description) and not bullets:
                issues.append(
                    self._issue(
                        ValidationSeverity.INFO,
                        ValidationCategory.PROJECT,
                        "Project entry has no description or bullet details.",
                        f"projects[{index}]",
                        "Leave blank only if the source resume has no project details.",
                    )
                )

            if not self._as_sequence(self._get(project, "technologies")):
                issues.append(
                    self._issue(
                        ValidationSeverity.INFO,
                        ValidationCategory.PROJECT,
                        "Project entry has no technologies listed.",
                        f"projects[{index}].technologies",
                        "Do not add technologies unless they are present in the source resume.",
                    )
                )

            if self._word_count(project) > _LARGE_SECTION_WORD_LIMIT:
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.FORMAT,
                        "Project entry is unusually large and may indicate a parsing failure.",
                        f"projects[{index}]",
                        "Review whether unrelated resume sections were merged into this project.",
                    )
                )

        issues.extend(
            self._duplicate_issues(
                project_names,
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.PROJECT,
                field_name="projects",
                label="project name",
            )
        )
        return issues

    def _validate_experience(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        experience_entries = self._as_sequence(self._get(resume, "experience"))
        employer_names: list[str] = []

        if not experience_entries:
            return [
                self._issue(
                    ValidationSeverity.INFO,
                    ValidationCategory.EXPERIENCE,
                    "Resume does not include work or internship experience.",
                    "experience",
                    "This is acceptable for early-career candidates.",
                )
            ]

        for index, experience in enumerate(experience_entries):
            organization = self._get(experience, "organization")
            if self._is_blank(organization):
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.EXPERIENCE,
                        "Experience entry is missing a company or organization.",
                        f"experience[{index}].organization",
                        "Review the parsed experience section.",
                    )
                )
            elif isinstance(organization, str):
                employer_names.append(organization.casefold())

            if self._is_blank(self._get(experience, "title")):
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.EXPERIENCE,
                        "Experience entry is missing a title.",
                        f"experience[{index}].title",
                        "Review the parsed experience section.",
                    )
                )

            if not self._as_sequence(self._get(experience, "bullets")):
                issues.append(
                    self._issue(
                        ValidationSeverity.INFO,
                        ValidationCategory.EXPERIENCE,
                        "Experience entry has no bullet point achievements.",
                        f"experience[{index}].bullets",
                        "Leave empty only if the source resume has no bullets for this role.",
                    )
                )

            if self._word_count(experience) > _LARGE_SECTION_WORD_LIMIT:
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.FORMAT,
                        "Experience entry is unusually large and may indicate a parsing failure.",
                        f"experience[{index}]",
                        "Review whether unrelated resume sections were merged into this role.",
                    )
                )

        issues.extend(
            self._duplicate_issues(
                employer_names,
                severity=ValidationSeverity.INFO,
                category=ValidationCategory.EXPERIENCE,
                field_name="experience",
                label="employer",
            )
        )
        return issues

    def _validate_certifications(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        certifications = self._as_sequence(self._get(resume, "certifications"))

        if not certifications:
            return [
                self._issue(
                    ValidationSeverity.INFO,
                    ValidationCategory.CERTIFICATION,
                    "Resume does not include certifications.",
                    "certifications",
                    "This is acceptable; do not add certifications unless present in the source.",
                )
            ]

        names = [
            str(self._get(certification, "name")).casefold()
            for certification in certifications
            if not self._is_blank(self._get(certification, "name"))
        ]
        issues.extend(
            self._duplicate_issues(
                names,
                severity=ValidationSeverity.WARNING,
                category=ValidationCategory.CERTIFICATION,
                field_name="certifications",
                label="certification",
            )
        )
        return issues

    def _validate_general_consistency(self, resume: Resume) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []

        if self._is_completely_empty(resume):
            issues.append(
                self._issue(
                    ValidationSeverity.ERROR,
                    ValidationCategory.GENERAL,
                    "Resume appears completely empty.",
                    None,
                    "Check document extraction and LLM parsing before downstream processing.",
                )
            )

        duplicate_entry_fields = {
            "education": ValidationCategory.EDUCATION,
            "projects": ValidationCategory.PROJECT,
            "experience": ValidationCategory.EXPERIENCE,
            "certifications": ValidationCategory.CERTIFICATION,
        }
        for field_name, category in duplicate_entry_fields.items():
            issues.extend(self._exact_duplicate_entry_issues(resume, field_name, category))

        section_lengths = {
            "summary": self._word_count(self._get(resume, "summary")),
            "education": self._word_count(self._get(resume, "education")),
            "projects": self._word_count(self._get(resume, "projects")),
            "experience": self._word_count(self._get(resume, "experience")),
            "skills": self._word_count(self._get(resume, "skills")),
        }
        for field_name, word_count in section_lengths.items():
            if word_count > _LARGE_SECTION_WORD_LIMIT:
                issues.append(
                    self._issue(
                        ValidationSeverity.WARNING,
                        ValidationCategory.FORMAT,
                        f"Section '{field_name}' is unusually large and may indicate "
                        "a parsing failure.",
                        field_name,
                        "Review whether multiple resume sections were merged incorrectly.",
                    )
                )

        if self._has_suspicious_single_blob(resume):
            issues.append(
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.GENERAL,
                    "Resume appears to contain a large text blob with few structured sections.",
                    None,
                    "Review parser output for suspicious extraction failures.",
                )
            )

        return issues

    def _validate_optional_profile_url(
        self,
        *,
        resume: Resume,
        field_name: str,
        label: str,
        expected_host: str,
    ) -> list[ValidationIssue]:
        value = self._get(resume, field_name)
        if self._is_blank(value):
            return [
                self._issue(
                    ValidationSeverity.INFO,
                    ValidationCategory.CONTACT,
                    f"Resume does not include a {label} URL.",
                    field_name,
                    f"This is acceptable; do not add a {label} URL unless present in the source.",
                )
            ]

        if not isinstance(value, str) or not self._is_valid_url(value, expected_host=expected_host):
            return [
                self._issue(
                    ValidationSeverity.WARNING,
                    ValidationCategory.CONTACT,
                    f"Resume {label} URL appears malformed.",
                    field_name,
                    f"Review the parsed {label} URL against the source resume.",
                )
            ]

        return []

    def _validate_education_years(self, education: object, index: int) -> list[ValidationIssue]:
        issues: list[ValidationIssue] = []
        current_year = date.today().year
        plausible_latest_year = current_year + 10

        for field_name in ("start_date", "end_date"):
            value = self._get(education, field_name)
            if not isinstance(value, str):
                continue
            for match in _YEAR_PATTERN.finditer(value):
                year = int(match.group("year"))
                if year < 1900 or year > plausible_latest_year:
                    issues.append(
                        self._issue(
                            ValidationSeverity.WARNING,
                            ValidationCategory.EDUCATION,
                            f"Education date contains an impossible graduation year: {year}.",
                            f"education[{index}].{field_name}",
                            "Review the parsed date against the source resume.",
                        )
                    )

        return issues

    def _collect_technologies(self, resume: Resume) -> list[str]:
        technologies: list[str] = []

        for project in self._as_sequence(self._get(resume, "projects")):
            for technology in self._as_sequence(self._get(project, "technologies")):
                if isinstance(technology, str) and technology.strip():
                    technologies.append(normalize_skill_name(technology))

        for experience in self._as_sequence(self._get(resume, "experience")):
            for technology in self._as_sequence(self._get(experience, "technologies")):
                if isinstance(technology, str) and technology.strip():
                    technologies.append(normalize_skill_name(technology))

        return technologies

    def _exact_duplicate_entry_issues(
        self,
        resume: Resume,
        field_name: str,
        category: ValidationCategory,
    ) -> list[ValidationIssue]:
        entries = self._as_sequence(self._get(resume, field_name))
        fingerprints = [self._fingerprint(entry) for entry in entries]
        return self._duplicate_issues(
            fingerprints,
            severity=ValidationSeverity.WARNING,
            category=category,
            field_name=field_name,
            label="exact duplicate entry",
        )

    def _duplicate_issues(
        self,
        values: Iterable[str],
        *,
        severity: ValidationSeverity,
        category: ValidationCategory,
        field_name: str,
        label: str,
    ) -> list[ValidationIssue]:
        counts = Counter(value for value in values if value)
        issues: list[ValidationIssue] = []
        for value, count in sorted(counts.items()):
            if count <= 1:
                continue
            issues.append(
                self._issue(
                    severity,
                    category,
                    f"Duplicate {label} detected: {value}",
                    field_name,
                    "Review duplicates against the source resume before downstream use.",
                )
            )
        return issues

    def _has_suspicious_single_blob(self, resume: Resume) -> bool:
        summary = self._get(resume, "summary")
        return (
            isinstance(summary, str)
            and self._word_count(summary) > 500
            and not self._as_sequence(self._get(resume, "education"))
            and not self._as_sequence(self._get(resume, "projects"))
            and not self._as_sequence(self._get(resume, "experience"))
            and not self._as_sequence(self._get(resume, "skills"))
        )

    def _is_completely_empty(self, resume: Resume) -> bool:
        fields = [
            self._get(resume, "full_name"),
            self._get(resume, "email"),
            self._get(resume, "phone"),
            self._get(resume, "location"),
            self._get(resume, "linkedin_url"),
            self._get(resume, "github_url"),
            self._get(resume, "links"),
            self._get(resume, "summary"),
            self._get(resume, "education"),
            self._get(resume, "experience"),
            self._get(resume, "projects"),
            self._get(resume, "certifications"),
            self._get(resume, "skills"),
        ]
        return all(self._is_blank(value) for value in fields)

    def _is_valid_url(self, value: str, *, expected_host: str | None = None) -> bool:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        if expected_host is None:
            return True
        return parsed.netloc.casefold().endswith(expected_host)

    def _word_count(self, value: object) -> int:
        if value is None:
            return 0
        if isinstance(value, str):
            return len(value.split())
        if isinstance(value, BaseModel):
            return self._word_count(value.model_dump(mode="python"))
        if isinstance(value, dict):
            return sum(self._word_count(item) for item in value.values())
        if isinstance(value, Sequence) and not isinstance(value, str):
            return sum(self._word_count(item) for item in value)
        return 0

    def _fingerprint(self, value: object) -> str:
        if isinstance(value, BaseModel):
            return value.model_dump_json(exclude_none=True)
        return repr(value)

    def _as_sequence(self, value: object) -> Sequence[Any]:
        if isinstance(value, Sequence) and not isinstance(value, str):
            return value
        return []

    def _get(self, value: object, field_name: str) -> object:
        if value is None:
            return None
        return getattr(value, field_name, None)

    def _is_blank(self, value: object) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, Sequence) and not isinstance(value, str):
            return len(value) == 0
        return False

    def _issue(
        self,
        severity: ValidationSeverity,
        category: ValidationCategory,
        message: str,
        field_name: str | None,
        suggestion: str | None,
    ) -> ValidationIssue:
        return ValidationIssue(
            severity=severity,
            category=category,
            message=message,
            field_name=field_name,
            suggestion=suggestion,
        )
