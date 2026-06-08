"""Structured job-description analysis and ATS scoring models."""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from ai_internship_assistant.domain.models.job import JobSeniority


class RequirementLevel(StrEnum):
    """How strongly a job posting requests a skill or qualification."""

    REQUIRED = "required"
    PREFERRED = "preferred"
    NICE_TO_HAVE = "nice_to_have"
    UNKNOWN = "unknown"


class RoleCategory(StrEnum):
    """Broad role categories supported by deterministic analysis."""

    CYBERSECURITY = "cybersecurity"
    SOFTWARE_ENGINEERING = "software_engineering"
    NETWORKING = "networking"
    IT_SUPPORT = "it_support"
    CLOUD = "cloud"
    DATA = "data"
    DEVOPS = "devops"
    UNKNOWN = "unknown"


class AnalysisSource(StrEnum):
    """Analyzer implementation that produced a job analysis."""

    RULE_BASED = "rule_based"
    LLM = "llm"
    HYBRID = "hybrid"


class SkillRequirement(BaseModel):
    """One extracted skill and the evidence supporting its requirement level."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    requirement_level: RequirementLevel = RequirementLevel.UNKNOWN
    evidence: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class AtsKeywordSet(BaseModel):
    """Compatibility keyword view retained for future ATS scoring."""

    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    action_verbs: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)


class JobAnalysis(BaseModel):
    """Structured, conservative analysis of a standardized job posting."""

    model_config = ConfigDict(extra="forbid")

    job_id: str
    job_title: str
    company: str
    normalized_title: str
    summary: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    required_skills: list[SkillRequirement] = Field(default_factory=list)
    preferred_skills: list[SkillRequirement] = Field(default_factory=list)
    technical_tools: list[str] = Field(default_factory=list)
    programming_languages: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    cloud_platforms: list[str] = Field(default_factory=list)
    cybersecurity_terms: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    ats_keywords: list[str] = Field(default_factory=list)
    experience_requirements: list[str] = Field(default_factory=list)
    education_requirements: list[str] = Field(default_factory=list)
    disqualifying_requirements: list[str] = Field(default_factory=list)
    internship_indicators: list[str] = Field(default_factory=list)
    seniority_indicators: list[str] = Field(default_factory=list)
    role_category: RoleCategory = RoleCategory.UNKNOWN
    domain_category: RoleCategory = RoleCategory.UNKNOWN
    seniority: JobSeniority = JobSeniority.UNKNOWN
    confidence_score: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)
    raw_text_hash: str
    analysis_source: AnalysisSource = AnalysisSource.RULE_BASED
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


JobDescriptionAnalysis = JobAnalysis


class AtsScore(BaseModel):
    """ATS compatibility score for a resume against a job posting."""

    overall_score: float = Field(ge=0.0, le=100.0)
    keyword_match_score: float = Field(ge=0.0, le=100.0)
    skills_match_score: float = Field(ge=0.0, le=100.0)
    formatting_score: float = Field(ge=0.0, le=100.0)
    missing_keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
