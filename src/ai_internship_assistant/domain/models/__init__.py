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
from ai_internship_assistant.domain.models.common import FileFormat, SourceFile
from ai_internship_assistant.domain.models.job import EmploymentType, JobPosting, JobSeniority
from ai_internship_assistant.domain.models.preferences import UserPreferences
from ai_internship_assistant.domain.models.resume import (
    Certification,
    Education,
    Experience,
    Project,
    Resume,
    ResumeSkill,
)

__all__ = [
    "ApplicationRecord",
    "ApplicationStatus",
    "AtsKeywordSet",
    "AtsScore",
    "Certification",
    "Education",
    "EmploymentType",
    "Experience",
    "FileFormat",
    "GeneratedResumeVersion",
    "JobDescriptionAnalysis",
    "JobPosting",
    "JobSeniority",
    "Project",
    "Resume",
    "ResumeSkill",
    "SourceFile",
    "UserPreferences",
]

