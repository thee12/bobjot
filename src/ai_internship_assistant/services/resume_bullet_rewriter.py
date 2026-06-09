"""Safe, isolated resume bullet rewriting with local post-generation validation."""

import os
import re
from collections.abc import Iterable, Sequence
from typing import Protocol, runtime_checkable

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from ai_internship_assistant.domain.models import (
    BulletRewriteRequest,
    BulletRewriteResult,
    BulletRewriteSource,
    KeywordInclusionStatus,
    ResumeOptimizationPlan,
    SafetyViolation,
    SafetyViolationSeverity,
    ViolationType,
)
from ai_internship_assistant.prompts import (
    BULLET_REWRITE_SYSTEM_PROMPT,
    build_bullet_rewrite_prompt,
)

_METRIC_PATTERN = re.compile(
    r"(?:\$\s?\d[\d,.]*|\b\d+(?:\.\d+)?%|\b\d+\+?\s+"
    r"(?:users?|customers?|tickets?|requests?|systems?|servers?|hours?|days?|weeks?)\b)",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"[a-z0-9+#]+", re.IGNORECASE)
_KNOWN_TECHNOLOGIES = (
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "C++",
    "C#",
    "Go",
    "Rust",
    "SQL",
    "Bash",
    "PowerShell",
    "Git",
    "GitHub",
    "Docker",
    "Kubernetes",
    "Linux",
    "Windows",
    "Splunk",
    "SIEM",
    "AWS",
    "Azure",
    "Google Cloud",
    "GCP",
    "FastAPI",
    "Flask",
    "Django",
    "React",
    "Node.js",
    "Spring Boot",
    "Wireshark",
    "Burp Suite",
    "Metasploit",
    "Nessus",
    "Qualys",
)
_EXPERIENCE_CLAIMS = (
    "enterprise security monitoring",
    "enterprise incident response",
    "production environment",
    "production systems",
    "soc operations",
    "threat hunting",
    "malware analysis",
    "penetration testing",
)
_ACTION_VERBS = {
    "analyzed",
    "assisted",
    "built",
    "captured",
    "collaborated",
    "configured",
    "created",
    "developed",
    "documented",
    "implemented",
    "improved",
    "investigated",
    "maintained",
    "monitored",
    "performed",
    "resolved",
    "supported",
    "tested",
    "troubleshot",
}
_MEANING_STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "the",
    "to",
    "using",
    "with",
    *_ACTION_VERBS,
}


def _contains_term(text: str, term: str) -> bool:
    pattern = re.escape(term.strip()).replace(r"\ ", r"\s+")
    return re.search(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", text, re.I) is not None


class _StructuredResponsesClient(Protocol):
    def parse(self, **kwargs: object) -> object:
        """Return one structured provider response."""


class _OpenAIClient(Protocol):
    responses: _StructuredResponsesClient


@runtime_checkable
class ResumeBulletRewriter(Protocol):
    """Replaceable interface for rewriting one resume bullet."""

    def rewrite(self, request: BulletRewriteRequest) -> BulletRewriteResult:
        """Rewrite or safely preserve one bullet."""


class BulletRewriteSafetyValidator:
    """Validate proposed bullet text against request evidence and constraints."""

    def validate(
        self,
        request: BulletRewriteRequest,
        proposed_bullet: str,
    ) -> list[SafetyViolation]:
        """Return all locally detectable safety violations."""

        proposed = proposed_bullet.strip()
        if not proposed:
            return [
                self._violation(
                    ViolationType.TOO_VAGUE,
                    "Proposed bullet is empty.",
                    proposed_bullet,
                )
            ]

        violations: list[SafetyViolation] = []
        if len(proposed) > request.max_length:
            violations.append(
                self._violation(
                    ViolationType.TOO_LONG,
                    f"Proposed bullet exceeds max length of {request.max_length}.",
                    proposed,
                )
            )
        for keyword in request.unsafe_keywords:
            if self._contains(proposed, keyword):
                violations.append(
                    self._violation(
                        ViolationType.UNSAFE_KEYWORD,
                        f"Proposed bullet includes unsafe keyword: {keyword}.",
                        keyword,
                    )
                )
        for claim in request.forbidden_claims:
            if claim.casefold() in proposed.casefold():
                violations.append(
                    self._violation(
                        ViolationType.FORBIDDEN_CLAIM,
                        "Proposed bullet includes a forbidden claim.",
                        claim,
                    )
                )
        violations.extend(self._invented_metrics(request, proposed))
        violations.extend(self._invented_technologies(request, proposed))
        violations.extend(self._invented_experience(request, proposed))
        violations.extend(self._meaning_violations(request, proposed))
        return self._deduplicate_violations(violations)

    def _invented_metrics(
        self,
        request: BulletRewriteRequest,
        proposed: str,
    ) -> list[SafetyViolation]:
        supported = self._metrics(
            " ".join([request.original_bullet, *request.candidate_evidence])
        )
        return [
            self._violation(
                ViolationType.INVENTED_METRIC,
                "Proposed bullet introduces a metric absent from candidate evidence.",
                metric,
            )
            for metric in self._metrics(proposed)
            if metric.casefold() not in {value.casefold() for value in supported}
        ]

    def _invented_technologies(
        self,
        request: BulletRewriteRequest,
        proposed: str,
    ) -> list[SafetyViolation]:
        allowed_text = " ".join(
            [
                request.original_bullet,
                *request.candidate_evidence,
                *request.safe_keywords,
                *request.related_keywords,
            ]
        )
        return [
            self._violation(
                ViolationType.INVENTED_TECHNOLOGY,
                "Proposed bullet introduces a technology absent from allowed evidence.",
                technology,
            )
            for technology in _KNOWN_TECHNOLOGIES
            if self._contains(proposed, technology) and not self._contains(allowed_text, technology)
        ]

    def _invented_experience(
        self,
        request: BulletRewriteRequest,
        proposed: str,
    ) -> list[SafetyViolation]:
        evidence = " ".join([request.original_bullet, *request.candidate_evidence])
        return [
            self._violation(
                ViolationType.INVENTED_EXPERIENCE,
                "Proposed bullet introduces unsupported experience scope.",
                claim,
            )
            for claim in _EXPERIENCE_CLAIMS
            if self._contains(proposed, claim) and not self._contains(evidence, claim)
        ]

    def _meaning_violations(
        self,
        request: BulletRewriteRequest,
        proposed: str,
    ) -> list[SafetyViolation]:
        words = self._significant_words(proposed)
        original_words = self._significant_words(request.original_bullet)
        violations: list[SafetyViolation] = []
        if len(words) < 3:
            violations.append(
                self._violation(
                    ViolationType.TOO_VAGUE,
                    "Proposed bullet is too vague to preserve meaningful evidence.",
                    proposed,
                )
            )
        if words and next(iter(self._words(proposed)), "") not in _ACTION_VERBS:
            violations.append(
                self._violation(
                    ViolationType.TOO_VAGUE,
                    "Proposed bullet does not start with a recognized action verb.",
                    proposed.split(maxsplit=1)[0],
                )
            )
        overlap = original_words & words
        minimum = 1 if len(original_words) <= 4 else max(2, round(len(original_words) * 0.25))
        if original_words and len(overlap) < minimum:
            violations.append(
                self._violation(
                    ViolationType.MEANING_CHANGED,
                    "Proposed bullet does not preserve enough of the original meaning.",
                    proposed,
                )
            )
        return violations

    def _metrics(self, value: str) -> list[str]:
        return [match.group(0) for match in _METRIC_PATTERN.finditer(value)]

    def _significant_words(self, value: str) -> set[str]:
        return {word for word in self._words(value) if word not in _MEANING_STOPWORDS}

    def _words(self, value: str) -> list[str]:
        return [word.casefold() for word in _WORD_PATTERN.findall(value)]

    def _contains(self, text: str, term: str) -> bool:
        return _contains_term(text, term)

    def _violation(
        self,
        violation_type: ViolationType,
        description: str,
        offending_text: str,
    ) -> SafetyViolation:
        return SafetyViolation(
            violation_type=violation_type,
            description=description,
            offending_text=offending_text,
            severity=SafetyViolationSeverity.ERROR,
        )

    def _deduplicate_violations(
        self,
        violations: Iterable[SafetyViolation],
    ) -> list[SafetyViolation]:
        result: list[SafetyViolation] = []
        seen: set[tuple[ViolationType, str]] = set()
        for violation in violations:
            key = (violation.violation_type, violation.offending_text.casefold())
            if key not in seen:
                seen.add(key)
                result.append(violation)
        return result


class RuleBasedResumeBulletRewriter:
    """Formatting-only safe fallback that never introduces new claims."""

    def rewrite(self, request: BulletRewriteRequest) -> BulletRewriteResult:
        """Normalize capitalization and punctuation while preserving content."""

        original = request.original_bullet.strip()
        rewritten = original[:1].upper() + original[1:] if original else original
        if (
            rewritten
            and rewritten[-1] not in ".!?"
            and len(rewritten) < request.max_length
        ):
            rewritten += "."
        changed = rewritten != original
        return BulletRewriteResult(
            original_bullet=original,
            rewritten_bullet=rewritten,
            changed=changed,
            included_keywords=self._included_keywords(request.safe_keywords, rewritten),
            avoided_keywords=[
                keyword
                for keyword in request.unsafe_keywords
                if not self._contains(rewritten, keyword)
            ],
            safety_violations=[],
            confidence_score=0.65 if changed else 0.45,
            explanation=(
                "Applied capitalization or punctuation only."
                if changed
                else (
                    "Preserved the original bullet because no safe deterministic "
                    "improvement exists."
                )
            ),
            warnings=["LLM rewrite unavailable; used formatting-only fallback."],
            rewrite_source=(
                BulletRewriteSource.RULE_BASED
                if changed
                else BulletRewriteSource.FALLBACK_ORIGINAL
            ),
        )

    def _included_keywords(self, keywords: Iterable[str], text: str) -> list[str]:
        return [keyword for keyword in keywords if self._contains(text, keyword)]

    def _contains(self, text: str, term: str) -> bool:
        return _contains_term(text, term)


class OpenAIResumeBulletRewriter:
    """OpenAI structured-output rewriter guarded by local safety validation."""

    def __init__(
        self,
        *,
        client: OpenAI | _OpenAIClient | None = None,
        api_key: str | None = None,
        model: str = "gpt-4.1-mini",
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
        validator: BulletRewriteSafetyValidator | None = None,
        fallback: ResumeBulletRewriter | None = None,
    ) -> None:
        """Create a provider-backed rewriter with a fail-closed fallback."""

        resolved_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client = client
        if self._client is None and resolved_key:
            self._client = OpenAI(api_key=resolved_key, timeout=timeout_seconds)
        self._model = model
        self._temperature = temperature
        self._validator = validator or BulletRewriteSafetyValidator()
        self._fallback = fallback or RuleBasedResumeBulletRewriter()

    def rewrite(self, request: BulletRewriteRequest) -> BulletRewriteResult:
        """Rewrite one bullet and reject any locally detected unsafe output."""

        if self._client is None:
            return self._provider_fallback(request, "OpenAI API key or client is unavailable.")
        try:
            response = self._client.responses.parse(
                model=self._model,
                instructions=BULLET_REWRITE_SYSTEM_PROMPT,
                input=build_bullet_rewrite_prompt(request),
                text_format=BulletRewriteResult,
                temperature=self._temperature,
            )
        except (OpenAIError, ValidationError) as exc:
            return self._provider_fallback(request, f"LLM bullet rewrite failed: {exc}")

        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, BulletRewriteResult):
            return self._provider_fallback(
                request,
                "LLM response did not contain a structured BulletRewriteResult.",
            )
        proposed = parsed.rewritten_bullet.strip()
        violations = self._validator.validate(request, proposed)
        if violations:
            return self._unsafe_fallback(request, violations)
        return BulletRewriteResult(
            original_bullet=request.original_bullet,
            rewritten_bullet=proposed,
            changed=proposed != request.original_bullet.strip(),
            included_keywords=self._included(request.safe_keywords, proposed),
            avoided_keywords=[
                keyword
                for keyword in request.unsafe_keywords
                if not self._contains(proposed, keyword)
            ],
            safety_violations=[],
            confidence_score=self._confidence(request, proposed),
            explanation=parsed.explanation or "Accepted after local safety validation.",
            warnings=list(parsed.warnings),
            rewrite_source=BulletRewriteSource.OPENAI,
        )

    def _provider_fallback(
        self,
        request: BulletRewriteRequest,
        warning: str,
    ) -> BulletRewriteResult:
        result = self._fallback.rewrite(request)
        return result.model_copy(update={"warnings": [*result.warnings, warning]})

    def _unsafe_fallback(
        self,
        request: BulletRewriteRequest,
        violations: Sequence[SafetyViolation],
    ) -> BulletRewriteResult:
        return BulletRewriteResult(
            original_bullet=request.original_bullet,
            rewritten_bullet=request.original_bullet,
            changed=False,
            included_keywords=self._included(request.safe_keywords, request.original_bullet),
            avoided_keywords=[
                keyword
                for keyword in request.unsafe_keywords
                if not self._contains(request.original_bullet, keyword)
            ],
            safety_violations=list(violations),
            confidence_score=0.1,
            explanation="Rejected proposed rewrite and preserved the original bullet.",
            warnings=["Proposed rewrite failed local safety validation."],
            rewrite_source=BulletRewriteSource.FALLBACK_ORIGINAL,
        )

    def _confidence(self, request: BulletRewriteRequest, proposed: str) -> float:
        score = 0.75
        score += min(len(self._included(request.safe_keywords, proposed)) * 0.04, 0.12)
        score += 0.05 if len(proposed) <= request.max_length else 0.0
        score -= min(len(request.unsafe_keywords) * 0.01, 0.1)
        return round(min(max(score, 0.0), 1.0), 2)

    def _included(self, keywords: Iterable[str], text: str) -> list[str]:
        return [keyword for keyword in keywords if self._contains(text, keyword)]

    def _contains(self, text: str, term: str) -> bool:
        return _contains_term(text, term)


def build_bullet_rewrite_request(
    *,
    original_bullet: str,
    section_name: str,
    parent_item_name: str,
    candidate_evidence: Sequence[str],
    plan: ResumeOptimizationPlan,
    max_length: int = 240,
    optimization_goal: str | None = None,
) -> BulletRewriteRequest:
    """Create a bullet request directly from the optimization-plan safety contract."""

    related = [
        item.keyword
        for item in plan.keyword_inclusion_plan
        if item.inclusion_status
        in {KeywordInclusionStatus.RELATED_ONLY, KeywordInclusionStatus.SAFE_TO_EMPHASIZE}
    ]
    return BulletRewriteRequest(
        original_bullet=original_bullet,
        section_name=section_name,
        parent_item_name=parent_item_name,
        candidate_evidence=list(candidate_evidence),
        target_job_title=plan.target_job_title,
        target_company=plan.target_company,
        safe_keywords=plan.safe_keywords,
        unsafe_keywords=plan.unsafe_keywords,
        forbidden_claims=plan.forbidden_claims,
        related_keywords=related,
        max_length=max_length,
        optimization_goal=optimization_goal
        or "Improve clarity and job relevance while preserving all original facts.",
    )
