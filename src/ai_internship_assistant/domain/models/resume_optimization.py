"""Strict safety contract for planning factual resume optimization."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class KeywordInclusionStatus(StrEnum):
    """Permission level for using a job keyword in future resume rewriting."""

    SAFE_TO_INCLUDE = "safe_to_include"
    SAFE_TO_EMPHASIZE = "safe_to_emphasize"
    RELATED_ONLY = "related_only"
    NOT_SAFE_TO_INCLUDE = "not_safe_to_include"
    LEARNING_RECOMMENDATION_ONLY = "learning_recommendation_only"


class PlanPriority(StrEnum):
    """Priority of an optimization plan or individual action."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    SKIP = "skip"


class RiskLevel(StrEnum):
    """Risk of creating an unsupported or misleading resume claim."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class SectionOptimizationPlan(BaseModel):
    """Planned action for one resume section without performing the edit."""

    model_config = ConfigDict(extra="forbid")

    section_name: str
    current_status: str
    recommended_action: str
    priority: PlanPriority
    evidence: list[str] = Field(default_factory=list)
    target_keywords: list[str] = Field(default_factory=list)
    forbidden_keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SkillReorderingPlan(BaseModel):
    """Safe ordering of skills already present in the resume."""

    model_config = ConfigDict(extra="forbid")

    original_skills: list[str] = Field(default_factory=list)
    recommended_order: list[str] = Field(default_factory=list)
    promoted_skills: list[str] = Field(default_factory=list)
    demoted_skills: list[str] = Field(default_factory=list)
    rationale: str


class ProjectEmphasisPlan(BaseModel):
    """Evidence-backed plan for positioning one existing project."""

    model_config = ConfigDict(extra="forbid")

    project_name: str
    relevance_score: float = Field(ge=0.0, le=100.0)
    related_job_keywords: list[str] = Field(default_factory=list)
    candidate_evidence: list[str] = Field(default_factory=list)
    recommended_strategy: str
    safe_phrasing_guidelines: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


class ExperienceEmphasisPlan(BaseModel):
    """Evidence-backed plan for positioning one existing experience entry."""

    model_config = ConfigDict(extra="forbid")

    experience_name: str
    relevance_score: float = Field(ge=0.0, le=100.0)
    related_job_keywords: list[str] = Field(default_factory=list)
    candidate_evidence: list[str] = Field(default_factory=list)
    recommended_strategy: str
    safe_phrasing_guidelines: list[str] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)


class KeywordInclusionPlan(BaseModel):
    """Explicit permission and evidence for one important job keyword."""

    model_config = ConfigDict(extra="forbid")

    keyword: str
    inclusion_status: KeywordInclusionStatus
    evidence_source: list[str] = Field(default_factory=list)
    target_sections: list[str] = Field(default_factory=list)
    safe_usage_guidance: str
    risk_level: RiskLevel


class ExpectedScoreImprovement(BaseModel):
    """Conservative estimated score-improvement range, not a promise."""

    model_config = ConfigDict(extra="forbid")

    low: float = Field(ge=0.0)
    high: float = Field(ge=0.0)
    rationale: str


class OptimizationRisk(BaseModel):
    """One factuality or eligibility risk and its mitigation."""

    model_config = ConfigDict(extra="forbid")

    description: str
    mitigation: str
    risk_level: RiskLevel


class ResumeOptimizationPlan(BaseModel):
    """Pre-rewrite permission contract for truthful resume tailoring."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    candidate_name: str | None = None
    target_job_title: str
    target_company: str
    baseline_ats_score: float = Field(ge=0.0, le=100.0)
    optimization_priority: PlanPriority
    plan_summary: str
    section_plans: list[SectionOptimizationPlan] = Field(default_factory=list)
    skill_reordering_plan: SkillReorderingPlan
    project_emphasis_plan: list[ProjectEmphasisPlan] = Field(default_factory=list)
    experience_emphasis_plan: list[ExperienceEmphasisPlan] = Field(default_factory=list)
    keyword_inclusion_plan: list[KeywordInclusionPlan] = Field(default_factory=list)
    forbidden_claims: list[str] = Field(default_factory=list)
    safe_keywords: list[str] = Field(default_factory=list)
    unsafe_keywords: list[str] = Field(default_factory=list)
    missing_skill_learning_recommendations: list[str] = Field(default_factory=list)
    expected_score_improvement: ExpectedScoreImprovement
    risks: list[OptimizationRisk] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    planner_version: str
