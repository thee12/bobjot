"""Deterministic candidate profile generation from validated resume evidence.

This module converts a detailed Resume into a normalized CandidateProfile for
future job discovery, ranking, ATS scoring, skill-gap analysis, optimization,
and recommendation workflows. It classifies existing evidence but never adds
skills, certifications, projects, technologies, education, or experience.

The rules-based implementation is deliberately provider-independent. Future
implementations can use local or hosted models behind the same generator
boundary while preserving the no-fabrication contract.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    CandidateProfile,
    ExperienceLevel,
    ProfileGenerationResult,
    ProfileValidationStatus,
    Resume,
    ValidationReport,
)
from ai_internship_assistant.services.resume_validation import ResumeValidator
from ai_internship_assistant.utils import normalize_skill_name

_DOMAIN_EVIDENCE: dict[CandidateDomain, set[str]] = {
    CandidateDomain.CYBERSECURITY: {
        "cybersecurity",
        "information security",
        "network security",
        "security+",
        "security plus",
        "soc",
        "siem",
        "vulnerability",
        "penetration testing",
        "incident response",
    },
    CandidateDomain.SOFTWARE_ENGINEERING: {
        "software engineering",
        "software development",
        "python",
        "java",
        "c++",
        "c#",
        "api",
        "fastapi",
        "flask",
        "spring boot",
    },
    CandidateDomain.DATA_SCIENCE: {
        "data science",
        "data analysis",
        "pandas",
        "numpy",
        "tableau",
        "statistics",
        "jupyter",
        "r programming",
    },
    CandidateDomain.CLOUD_ENGINEERING: {
        "cloud",
        "aws",
        "azure",
        "google cloud",
        "gcp",
        "terraform",
        "cloudformation",
    },
    CandidateDomain.NETWORKING: {
        "networking",
        "network operations",
        "routing",
        "switching",
        "cisco",
        "ccna",
        "tcp/ip",
        "dns",
        "dhcp",
    },
    CandidateDomain.DEVOPS: {
        "devops",
        "ci/cd",
        "github actions",
        "docker",
        "kubernetes",
        "jenkins",
        "terraform",
    },
    CandidateDomain.MACHINE_LEARNING: {
        "machine learning",
        "tensorflow",
        "pytorch",
        "scikit-learn",
        "deep learning",
        "model training",
    },
    CandidateDomain.IT_SUPPORT: {
        "it support",
        "help desk",
        "technical support",
        "troubleshooting",
        "ticket",
        "desktop support",
    },
    CandidateDomain.SYSTEMS_ADMINISTRATION: {
        "systems administration",
        "system administration",
        "active directory",
        "windows server",
        "linux administration",
        "powershell",
    },
    CandidateDomain.WEB_DEVELOPMENT: {
        "web development",
        "javascript",
        "typescript",
        "react",
        "node.js",
        "html",
        "css",
        "django",
    },
}

_DOMAIN_ROLES: dict[CandidateDomain, list[str]] = {
    CandidateDomain.CYBERSECURITY: [
        "Cybersecurity Intern",
        "SOC Analyst Intern",
        "Security Engineering Intern",
    ],
    CandidateDomain.SOFTWARE_ENGINEERING: [
        "Software Engineering Intern",
        "Software Developer Intern",
    ],
    CandidateDomain.DATA_SCIENCE: ["Data Science Intern", "Data Analyst Intern"],
    CandidateDomain.CLOUD_ENGINEERING: ["Cloud Engineering Intern", "Cloud Operations Intern"],
    CandidateDomain.NETWORKING: ["Network Operations Intern", "Network Engineering Intern"],
    CandidateDomain.DEVOPS: ["DevOps Intern", "Platform Engineering Intern"],
    CandidateDomain.MACHINE_LEARNING: ["Machine Learning Intern", "AI Engineering Intern"],
    CandidateDomain.IT_SUPPORT: ["IT Support Intern", "Technical Support Intern"],
    CandidateDomain.SYSTEMS_ADMINISTRATION: [
        "Systems Administration Intern",
        "Infrastructure Intern",
    ],
    CandidateDomain.WEB_DEVELOPMENT: ["Web Development Intern", "Frontend Development Intern"],
    CandidateDomain.GENERAL_TECHNOLOGY: ["Technology Intern"],
}

_SUPPORTING_SKILLS = {
    "figma",
    "git",
    "github",
    "jira",
    "microsoft office",
    "postman",
    "visual studio code",
    "vs code",
}


class CandidateProfileGenerationError(TypeError):
    """Raised when profile generation receives an invalid programmer input."""


class ProfileGenerator(Protocol):
    """Extension point for future candidate profile generator implementations."""

    def generate(
        self,
        resume: Resume,
        validation_report: ValidationReport | None = None,
    ) -> CandidateProfile:
        """Generate a normalized candidate profile from resume evidence."""


class CandidateProfileGenerator:
    """Rules-based candidate profile generator.

    The generator consumes a Resume and its ValidationReport. If no report is
    supplied, it validates the resume first. Generation degrades gracefully for
    incomplete resumes and lowers confidence when validation issues are present.
    """

    def __init__(self, validator: ResumeValidator | None = None) -> None:
        self._validator = validator or ResumeValidator()

    def generate(
        self,
        resume: Resume,
        validation_report: ValidationReport | None = None,
    ) -> CandidateProfile:
        """Generate a CandidateProfile derived only from Resume evidence."""

        if resume is None or not isinstance(resume, Resume):
            msg = "resume must be a Resume instance"
            raise CandidateProfileGenerationError(msg)
        if validation_report is not None and not isinstance(validation_report, ValidationReport):
            msg = "validation_report must be a ValidationReport instance"
            raise CandidateProfileGenerationError(msg)

        report = validation_report or self._validator.validate(resume)
        domains = self._classify_domains(resume)
        primary_domain = domains[0]
        secondary_domains = domains[1:4]
        core_skills, supporting_skills = self._organize_skills(resume)
        technologies = self._collect_technologies(resume)
        experience_level = self._classify_experience_level(resume)
        target_roles = self._target_roles(primary_domain, secondary_domains)

        return CandidateProfile(
            candidate_name=resume.full_name,
            experience_level=experience_level,
            primary_domain=primary_domain,
            secondary_domains=secondary_domains,
            core_skills=core_skills,
            supporting_skills=supporting_skills,
            certifications=self._certification_names(resume),
            technologies=technologies,
            target_roles=target_roles,
            industry_keywords=[
                domain.value
                for domain in domains
                if domain != CandidateDomain.GENERAL_TECHNOLOGY
            ],
            search_keywords=target_roles.copy(),
            education_level=self._education_level(resume),
            confidence_score=self._confidence_score(resume, report),
            profile_summary=self._profile_summary(
                resume=resume,
                experience_level=experience_level,
                primary_domain=primary_domain,
                core_skills=core_skills,
            ),
            validation_status=self._validation_status(report),
            validation_messages=[issue.message for issue in report.issues],
        )

    def _classify_domains(self, resume: Resume) -> list[CandidateDomain]:
        evidence = self._evidence_text(resume)
        scores: Counter[CandidateDomain] = Counter()

        for domain, keywords in _DOMAIN_EVIDENCE.items():
            scores[domain] = sum(1 for keyword in keywords if keyword in evidence)

        ranked_domains = [
            domain
            for domain, score in sorted(
                scores.items(),
                key=lambda item: (-item[1], item[0].value),
            )
            if score > 0
        ]
        return ranked_domains or [CandidateDomain.GENERAL_TECHNOLOGY]

    def _organize_skills(self, resume: Resume) -> tuple[list[str], list[str]]:
        core: list[str] = []
        supporting: list[str] = []
        seen: set[str] = set()

        for skill in resume.skills:
            normalized = normalize_skill_name(skill.name)
            if normalized.casefold() in seen:
                continue
            seen.add(normalized.casefold())
            destination = supporting if normalized.casefold() in _SUPPORTING_SKILLS else core
            destination.append(skill.name)

        return core, supporting

    def _collect_technologies(self, resume: Resume) -> list[str]:
        values: list[str] = [skill.name for skill in resume.skills]
        for project in resume.projects:
            values.extend(project.technologies)
        for experience in resume.experience:
            values.extend(experience.technologies)
        return self._deduplicate_preserving_source(values)

    def _certification_names(self, resume: Resume) -> list[str]:
        return self._deduplicate_preserving_source(
            certification.name for certification in resume.certifications
        )

    def _classify_experience_level(self, resume: Resume) -> ExperienceLevel:
        titles = " ".join(experience.title.casefold() for experience in resume.experience)

        if any(keyword in titles for keyword in ("senior", "staff", "principal", "lead")):
            return ExperienceLevel.SENIOR
        if "mid-level" in titles or "mid level" in titles:
            return ExperienceLevel.MID_LEVEL
        if "junior" in titles:
            return ExperienceLevel.JUNIOR
        if "entry level" in titles or "entry-level" in titles or "associate" in titles:
            return ExperienceLevel.ENTRY_LEVEL
        if "intern" in titles:
            return ExperienceLevel.INTERNSHIP
        if resume.experience:
            return ExperienceLevel.ENTRY_LEVEL
        return ExperienceLevel.STUDENT

    def _target_roles(
        self,
        primary_domain: CandidateDomain,
        secondary_domains: Sequence[CandidateDomain],
    ) -> list[str]:
        roles = list(_DOMAIN_ROLES[primary_domain])
        for domain in secondary_domains:
            roles.extend(_DOMAIN_ROLES[domain][:1])
        return self._deduplicate_preserving_source(roles)

    def _education_level(self, resume: Resume) -> str | None:
        degree_text = " ".join(
            part
            for education in resume.education
            for part in (education.degree, education.program)
            if part is not None
        ).casefold()

        mappings = [
            (("phd", "ph.d", "doctorate", "doctoral"), "Doctorate"),
            (("master", "m.s.", "m.a.", "mba"), "Master's"),
            (("bachelor", "b.s.", "b.a.", "bsc"), "Bachelor's"),
            (("associate", "a.s.", "a.a."), "Associate"),
            (("high school", "ged"), "High School"),
        ]
        for keywords, level in mappings:
            if any(keyword in degree_text for keyword in keywords):
                return level
        return None

    def _confidence_score(self, resume: Resume, report: ValidationReport) -> float:
        score = 0.35
        score += 0.1 if resume.full_name else 0.0
        score += 0.1 if resume.email else 0.0
        score += 0.1 if resume.education else 0.0
        score += 0.15 if resume.skills else 0.0
        score += 0.1 if resume.projects else 0.0
        score += 0.1 if resume.experience else 0.0
        score -= min(report.warning_count * 0.03, 0.3)
        score -= min(report.error_count * 0.2, 0.6)
        return round(min(max(score, 0.0), 1.0), 2)

    def _profile_summary(
        self,
        *,
        resume: Resume,
        experience_level: ExperienceLevel,
        primary_domain: CandidateDomain,
        core_skills: Sequence[str],
    ) -> str:
        subject = resume.full_name or "Candidate"
        level_label = experience_level.value.replace("_", " ")
        summary = f"{subject} is classified at the {level_label} level"

        if primary_domain != CandidateDomain.GENERAL_TECHNOLOGY:
            summary += f" with resume evidence aligned to {primary_domain.value}"

        if core_skills:
            summary += f", including {', '.join(core_skills[:3])}"

        return f"{summary}."

    def _validation_status(self, report: ValidationReport) -> ProfileValidationStatus:
        if report.error_count:
            return ProfileValidationStatus.HAS_ERRORS
        if report.warning_count:
            return ProfileValidationStatus.HAS_WARNINGS
        return ProfileValidationStatus.CLEAN

    def _evidence_text(self, resume: Resume) -> str:
        values: list[str] = []
        values.extend(skill.name for skill in resume.skills)
        values.extend(certification.name for certification in resume.certifications)

        for education in resume.education:
            values.extend(
                part
                for part in (education.degree, education.program, *education.details)
                if part is not None
            )
        for project in resume.projects:
            values.extend(
                part
                for part in (
                    project.name,
                    project.description,
                    *project.bullets,
                    *project.technologies,
                )
                if part is not None
            )
        for experience in resume.experience:
            values.extend(
                (
                    experience.title,
                    experience.organization,
                    *experience.bullets,
                    *experience.technologies,
                )
            )

        return " ".join(values).casefold()

    def _deduplicate_preserving_source(self, values: Iterable[str]) -> list[str]:
        deduplicated: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = normalize_skill_name(value).casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(value)
        return deduplicated


class CandidateProfilePipeline:
    """Validate a Resume and generate its CandidateProfile in one operation."""

    def __init__(
        self,
        *,
        validator: ResumeValidator | None = None,
        generator: CandidateProfileGenerator | None = None,
    ) -> None:
        self._validator = validator or ResumeValidator()
        self._generator = generator or CandidateProfileGenerator(self._validator)

    def run(self, resume: Resume) -> ProfileGenerationResult:
        """Return a profile and its independently consumable validation report."""

        validation_report = self._validator.validate(resume)
        profile = self._generator.generate(resume, validation_report)
        return ProfileGenerationResult(profile=profile, validation_report=validation_report)
