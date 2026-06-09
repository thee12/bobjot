"""Models for safe, isolated resume bullet rewriting."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class BulletRewriteSource(StrEnum):
    """Implementation or fallback that produced a bullet result."""

    OPENAI = "openai"
    RULE_BASED = "rule_based"
    FALLBACK_ORIGINAL = "fallback_original"


class ViolationType(StrEnum):
    """Locally detected safety failure in a proposed rewritten bullet."""

    INVENTED_TECHNOLOGY = "invented_technology"
    INVENTED_METRIC = "invented_metric"
    INVENTED_EXPERIENCE = "invented_experience"
    FORBIDDEN_CLAIM = "forbidden_claim"
    UNSAFE_KEYWORD = "unsafe_keyword"
    MEANING_CHANGED = "meaning_changed"
    TOO_LONG = "too_long"
    TOO_VAGUE = "too_vague"


class SafetyViolationSeverity(StrEnum):
    """Severity of a detected bullet safety violation."""

    WARNING = "warning"
    ERROR = "error"


class SafetyViolation(BaseModel):
    """One locally detected reason a proposed rewrite cannot be accepted."""

    model_config = ConfigDict(extra="forbid")

    violation_type: ViolationType
    description: str
    offending_text: str
    severity: SafetyViolationSeverity


class BulletRewriteRequest(BaseModel):
    """Evidence and permissions for rewriting exactly one resume bullet."""

    model_config = ConfigDict(extra="forbid")

    original_bullet: str = Field(min_length=1)
    section_name: str = Field(min_length=1)
    parent_item_name: str = Field(min_length=1)
    candidate_evidence: list[str] = Field(default_factory=list)
    target_job_title: str = Field(min_length=1)
    target_company: str = Field(min_length=1)
    safe_keywords: list[str] = Field(default_factory=list)
    unsafe_keywords: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    related_keywords: list[str] = Field(default_factory=list)
    desired_tone: str = "concise, action-oriented, internship-appropriate"
    max_length: int = Field(default=240, ge=40, le=1_000)
    optimization_goal: str = Field(
        default="Improve clarity and target-job relevance while preserving all facts.",
        min_length=1,
    )


class BulletRewriteResult(BaseModel):
    """Validated result for one bullet rewrite attempt."""

    model_config = ConfigDict(extra="forbid")

    original_bullet: str
    rewritten_bullet: str
    changed: bool
    included_keywords: list[str] = Field(default_factory=list)
    avoided_keywords: list[str] = Field(default_factory=list)
    safety_violations: list[SafetyViolation] = Field(default_factory=list)
    confidence_score: float = Field(ge=0.0, le=1.0)
    explanation: str
    warnings: list[str] = Field(default_factory=list)
    rewrite_source: BulletRewriteSource
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
