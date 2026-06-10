"""Persistence adapters and repository entrypoints."""

from ai_internship_assistant.storage.application_repositories import (
    ApplicationNotFoundError,
    ApplicationRepository,
    SavedJobNotFoundError,
    SavedJobRepository,
)
from ai_internship_assistant.storage.database import (
    Database,
    DatabaseUnavailableError,
)
from ai_internship_assistant.storage.pipeline_run_repository import (
    PipelineRunNotFoundError,
    PipelineRunRepository,
    PipelineRunStateError,
)
from ai_internship_assistant.storage.repositories import (
    CorruptedArtifactError,
    DuplicateMasterResumeError,
    JobNotFoundError,
    JobRepository,
    MasterResumeNotFoundError,
    MasterResumeRepository,
    PersistenceError,
    ResumeVersionNotFoundError,
    ResumeVersionRepository,
)
from ai_internship_assistant.storage.serialization import (
    ArtifactSerializationError,
    normalized_text_hash,
    structured_content_hash,
)

__all__ = [
    "ArtifactSerializationError",
    "ApplicationNotFoundError",
    "ApplicationRepository",
    "CorruptedArtifactError",
    "Database",
    "DatabaseUnavailableError",
    "DuplicateMasterResumeError",
    "JobNotFoundError",
    "JobRepository",
    "MasterResumeNotFoundError",
    "MasterResumeRepository",
    "PersistenceError",
    "PipelineRunNotFoundError",
    "PipelineRunRepository",
    "PipelineRunStateError",
    "ResumeVersionNotFoundError",
    "ResumeVersionRepository",
    "SavedJobNotFoundError",
    "SavedJobRepository",
    "normalized_text_hash",
    "structured_content_hash",
]
