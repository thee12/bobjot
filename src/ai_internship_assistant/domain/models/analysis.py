"""Models for job description analysis and ATS scoring outputs."""

from pydantic import BaseModel, Field


class AtsKeywordSet(BaseModel):
    """Keywords and signals extracted from a job description."""

    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    technologies: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    action_verbs: list[str] = Field(default_factory=list)
    domain_keywords: list[str] = Field(default_factory=list)


class JobDescriptionAnalysis(BaseModel):
    """Structured analysis of a job description."""

    keywords: AtsKeywordSet = Field(default_factory=AtsKeywordSet)
    responsibilities: list[str] = Field(default_factory=list)
    qualifications: list[str] = Field(default_factory=list)
    disqualifying_constraints: list[str] = Field(default_factory=list)


class AtsScore(BaseModel):
    """ATS compatibility score for a resume against a job posting."""

    overall_score: float = Field(ge=0.0, le=100.0)
    keyword_match_score: float = Field(ge=0.0, le=100.0)
    skills_match_score: float = Field(ge=0.0, le=100.0)
    formatting_score: float = Field(ge=0.0, le=100.0)
    missing_keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

