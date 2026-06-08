"""OpenAI and hybrid structured job-description analyzers.

Only job-posting fields are sent to the provider. Resume and candidate data are
outside this service boundary. Provider failures are represented with specific
exceptions so the hybrid analyzer can reliably fall back to deterministic
analysis.
"""

import os
from collections.abc import Iterable, Sequence
from typing import Protocol

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from ai_internship_assistant.domain.models import (
    AnalysisSource,
    JobAnalysis,
    JobPosting,
    JobSeniority,
    RequirementLevel,
    RoleCategory,
    SkillRequirement,
)
from ai_internship_assistant.prompts import (
    JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT,
    build_job_description_analysis_prompt,
)
from ai_internship_assistant.services.job_description_analyzer import (
    JobDescriptionAnalyzer,
    RuleBasedJobDescriptionAnalyzer,
)

_MAX_EVIDENCE_LENGTH = 300


class _StructuredResponsesClient(Protocol):
    def parse(self, **kwargs: object) -> object:
        """Return one structured provider response."""


class _OpenAIClient(Protocol):
    responses: _StructuredResponsesClient


class JobDescriptionAnalysisError(RuntimeError):
    """Base exception for provider-backed job-description analysis failures."""


class MissingJobAnalysisAPIKeyError(JobDescriptionAnalysisError):
    """Raised when OpenAI analysis is requested without an API key or client."""


class EmptyJobDescriptionError(JobDescriptionAnalysisError):
    """Raised when a posting contains no analyzable job-description content."""


class LLMJobDescriptionAnalysisError(JobDescriptionAnalysisError):
    """Raised when the LLM provider fails during job analysis."""


class MalformedJobAnalysisResponseError(JobDescriptionAnalysisError):
    """Raised when provider output cannot be validated as JobAnalysis."""


class OpenAIJobDescriptionAnalyzer:
    """OpenAI structured-output analyzer for standardized job postings."""

    def __init__(
        self,
        *,
        client: OpenAI | _OpenAIClient | None = None,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
        max_input_length: int = 30_000,
    ) -> None:
        """Create an analyzer with safe deterministic defaults."""

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        if self._client is None and resolved_key:
            self._client = OpenAI(api_key=resolved_key, timeout=timeout_seconds)
        self._model = model
        self._temperature = temperature
        self._max_input_length = max_input_length
        self._rule_analyzer = RuleBasedJobDescriptionAnalyzer()

    def analyze(self, job: JobPosting) -> JobAnalysis:
        """Analyze one posting using OpenAI structured outputs."""

        baseline = self._rule_analyzer.analyze(job)
        if not self._has_analyzable_content(job):
            msg = "job posting contains no analyzable description content"
            raise EmptyJobDescriptionError(msg)
        if self._client is None:
            msg = "OpenAI job analysis requires OPENAI_API_KEY or an injected client"
            raise MissingJobAnalysisAPIKeyError(msg)

        prompt = build_job_description_analysis_prompt(
            job,
            max_length=self._max_input_length,
        )
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=JOB_DESCRIPTION_ANALYSIS_SYSTEM_PROMPT,
                input=prompt,
                text_format=JobAnalysis,
                temperature=self._temperature,
            )
        except ValidationError as exc:
            msg = "OpenAI returned job analysis that failed schema validation"
            raise MalformedJobAnalysisResponseError(msg) from exc
        except OpenAIError as exc:
            msg = "OpenAI failed while analyzing the job description"
            raise LLMJobDescriptionAnalysisError(msg) from exc

        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, JobAnalysis):
            msg = "OpenAI response did not contain a parsed JobAnalysis object"
            raise MalformedJobAnalysisResponseError(msg)
        return self._sanitize(parsed, baseline, prompt)

    def _sanitize(
        self,
        parsed: JobAnalysis,
        baseline: JobAnalysis,
        prompt: str,
    ) -> JobAnalysis:
        required = self._sanitize_requirements(parsed.required_skills, prompt)
        preferred = self._sanitize_requirements(parsed.preferred_skills, prompt)
        preferred = [
            item
            for item in preferred
            if self._normalize(item.name) not in {self._normalize(item.name) for item in required}
        ]
        warnings = list(parsed.warnings)
        if len(required) + len(preferred) < len(parsed.required_skills) + len(
            parsed.preferred_skills
        ):
            warnings.append("unsupported LLM skill requirements were discarded")
        if "[INPUT TRUNCATED" in prompt:
            warnings.append("LLM analysis input was truncated")

        return parsed.model_copy(
            update={
                "job_id": baseline.job_id,
                "job_title": baseline.job_title,
                "company": baseline.company,
                "normalized_title": baseline.normalized_title,
                "required_skills": required,
                "preferred_skills": preferred,
                "warnings": self._deduplicate(warnings),
                "raw_text_hash": baseline.raw_text_hash,
                "analysis_source": AnalysisSource.LLM,
            }
        )

    def _sanitize_requirements(
        self,
        requirements: Sequence[SkillRequirement],
        prompt: str,
    ) -> list[SkillRequirement]:
        result: list[SkillRequirement] = []
        seen: set[str] = set()
        for requirement in requirements:
            normalized = self._normalize(requirement.name)
            if not normalized or normalized in seen:
                continue
            evidence = requirement.evidence[:_MAX_EVIDENCE_LENGTH].strip()
            name_is_supported = self._appears_in_prompt(requirement.name, prompt)
            evidence_is_supported = self._appears_in_prompt(evidence, prompt)
            if not name_is_supported and not evidence_is_supported:
                continue
            seen.add(normalized)
            result.append(
                requirement.model_copy(
                    update={"evidence": evidence or requirement.name}
                )
            )
        return result

    def _appears_in_prompt(self, value: str, prompt: str) -> bool:
        return bool(value.strip()) and value.casefold() in prompt.casefold()

    def _has_analyzable_content(self, job: JobPosting) -> bool:
        return any(
            (
                job.description,
                job.responsibilities,
                job.requirements,
                job.preferred_qualifications,
                job.technologies,
                job.certifications,
            )
        )

    def _normalize(self, value: str) -> str:
        return " ".join(value.casefold().split())

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result


class HybridJobDescriptionAnalyzer:
    """Conservatively merge rule-based and LLM job-description analysis."""

    def __init__(
        self,
        *,
        rule_analyzer: JobDescriptionAnalyzer | None = None,
        llm_analyzer: JobDescriptionAnalyzer | None = None,
    ) -> None:
        """Create a hybrid analyzer with replaceable implementations."""

        self._rule_analyzer = rule_analyzer or RuleBasedJobDescriptionAnalyzer()
        self._llm_analyzer = llm_analyzer or OpenAIJobDescriptionAnalyzer()

    def analyze(self, job: JobPosting) -> JobAnalysis:
        """Analyze with both implementations and fall back on provider failure."""

        rule = self._rule_analyzer.analyze(job)
        try:
            llm = self._llm_analyzer.analyze(job)
        except JobDescriptionAnalysisError as exc:
            return rule.model_copy(
                update={
                    "warnings": self._union(
                        rule.warnings,
                        [f"LLM analysis unavailable; used rule-based fallback: {exc}"],
                    ),
                    "analysis_source": AnalysisSource.RULE_BASED,
                }
            )
        return self._merge(rule, llm)

    def _merge(self, rule: JobAnalysis, llm: JobAnalysis) -> JobAnalysis:
        required, preferred = self._merge_requirements(
            rule.required_skills,
            rule.preferred_skills,
            llm.required_skills,
            llm.preferred_skills,
        )
        role = self._prefer_role(llm.role_category, rule.role_category)
        domain = self._prefer_role(llm.domain_category, rule.domain_category)
        seniority = self._prefer_seniority(llm.seniority, rule.seniority)
        agreement_penalty = sum(
            (
                0.08 if self._disagrees(rule.role_category, llm.role_category) else 0.0,
                0.08 if self._disagrees(rule.domain_category, llm.domain_category) else 0.0,
                0.08 if self._disagrees(rule.seniority, llm.seniority) else 0.0,
            )
        )
        confidence = max(0.0, min(1.0, (rule.confidence_score + llm.confidence_score) / 2))
        confidence = round(max(0.0, confidence - agreement_penalty), 2)

        list_fields = (
            "technical_tools",
            "programming_languages",
            "frameworks",
            "cloud_platforms",
            "cybersecurity_terms",
            "certifications",
            "soft_skills",
            "ats_keywords",
            "experience_requirements",
            "education_requirements",
            "disqualifying_requirements",
            "internship_indicators",
            "seniority_indicators",
        )
        updates: dict[str, object] = {
            field: self._union(getattr(llm, field), getattr(rule, field)) for field in list_fields
        }
        updates.update(
            {
                "summary": llm.summary or rule.summary,
                "responsibilities": llm.responsibilities or rule.responsibilities,
                "qualifications": llm.qualifications or rule.qualifications,
                "required_skills": required,
                "preferred_skills": preferred,
                "role_category": role,
                "domain_category": domain,
                "seniority": seniority,
                "confidence_score": confidence,
                "warnings": self._union(llm.warnings, rule.warnings),
                "analysis_source": AnalysisSource.HYBRID,
            }
        )
        return rule.model_copy(update=updates)

    def _merge_requirements(
        self,
        rule_required: Sequence[SkillRequirement],
        rule_preferred: Sequence[SkillRequirement],
        llm_required: Sequence[SkillRequirement],
        llm_preferred: Sequence[SkillRequirement],
    ) -> tuple[list[SkillRequirement], list[SkillRequirement]]:
        selected: dict[str, SkillRequirement] = {}
        for requirement in [*llm_required, *llm_preferred, *rule_required, *rule_preferred]:
            selected.setdefault(self._normalize(requirement.name), requirement)

        required = [
            requirement
            for requirement in selected.values()
            if requirement.requirement_level == RequirementLevel.REQUIRED
        ]
        preferred = [
            requirement
            for requirement in selected.values()
            if requirement.requirement_level
            in {RequirementLevel.PREFERRED, RequirementLevel.NICE_TO_HAVE}
        ]
        return required, preferred

    def _prefer_role(self, preferred: RoleCategory, fallback: RoleCategory) -> RoleCategory:
        return preferred if preferred != RoleCategory.UNKNOWN else fallback

    def _prefer_seniority(
        self,
        preferred: JobSeniority,
        fallback: JobSeniority,
    ) -> JobSeniority:
        return preferred if preferred != JobSeniority.UNKNOWN else fallback

    def _disagrees(
        self,
        first: RoleCategory | JobSeniority,
        second: RoleCategory | JobSeniority,
    ) -> bool:
        unknown = {RoleCategory.UNKNOWN, JobSeniority.UNKNOWN}
        return first not in unknown and second not in unknown and first != second

    def _union(self, primary: Iterable[str], secondary: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in [*primary, *secondary]:
            normalized = self._normalize(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result

    def _normalize(self, value: str) -> str:
        return " ".join(value.casefold().split())
