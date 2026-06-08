"""Core Pydantic models for resumes, jobs, ATS analysis, and applications."""

from ai_internship_assistant.domain.models.analysis import (
    AtsKeywordSet,
    AtsScore,
    JobDescriptionAnalysis,
)
from ai_internship_assistant.domain.models.application import (
    ApplicationRecord,
    ApplicationStatus,
    GeneratedResumeVersion,
)
from ai_internship_assistant.domain.models.candidate_profile import (
    CandidateDomain,
    CandidateProfile,
    ExperienceLevel,
    ProfileGenerationResult,
    ProfileValidationStatus,
)
from ai_internship_assistant.domain.models.common import FileFormat, SourceFile
from ai_internship_assistant.domain.models.job import (
    EmploymentType,
    JobDeduplicationGroup,
    JobDeduplicationResult,
    JobPosting,
    JobSearchErrorType,
    JobSearchResultSet,
    JobSeniority,
    JobSourceError,
    JobSourceSearchResult,
    JobSourceType,
    NormalizedJobPosting,
    WorkArrangement,
)
from ai_internship_assistant.domain.models.job_ranking import (
    JobFitScore,
    RankedJobResult,
    RankedJobResultSet,
    RecommendationLevel,
)
from ai_internship_assistant.domain.models.job_search import (
    JobSearchPreferences,
    JobSearchQuery,
    JobSearchQuerySet,
    QueryPriority,
    RemotePreference,
    SearchEmploymentType,
)
from ai_internship_assistant.domain.models.preferences import UserPreferences
from ai_internship_assistant.domain.models.resume import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
    ResumeSkill,
    Skill,
)
from ai_internship_assistant.domain.models.validation import (
    ValidationCategory,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)

__all__ = [
    "ApplicationRecord",
    "ApplicationStatus",
    "AtsKeywordSet",
    "AtsScore",
    "Certification",
    "CandidateDomain",
    "CandidateProfile",
    "Education",
    "EmploymentType",
    "ExperienceLevel",
    "Experience",
    "FileFormat",
    "GeneratedResumeVersion",
    "JobDescriptionAnalysis",
    "JobDeduplicationGroup",
    "JobDeduplicationResult",
    "JobPosting",
    "JobFitScore",
    "JobSearchErrorType",
    "JobSearchResultSet",
    "JobSearchPreferences",
    "JobSearchQuery",
    "JobSearchQuerySet",
    "JobSeniority",
    "JobSourceError",
    "JobSourceSearchResult",
    "JobSourceType",
    "NormalizedJobPosting",
    "Project",
    "ProfileGenerationResult",
    "ProfileValidationStatus",
    "Resume",
    "ResumeSkill",
    "QueryPriority",
    "RankedJobResult",
    "RankedJobResultSet",
    "RecommendationLevel",
    "RemotePreference",
    "SearchEmploymentType",
    "Skill",
    "SourceFile",
    "UserPreferences",
    "ValidationCategory",
    "ValidationIssue",
    "ValidationReport",
    "ValidationSeverity",
    "WorkArrangement",
]
