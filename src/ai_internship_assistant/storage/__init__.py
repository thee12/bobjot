"""Persistence adapters and repository entrypoints."""

from ai_internship_assistant.storage.database import (
    Database,
    DatabaseUnavailableError,
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
    "CorruptedArtifactError",
    "Database",
    "DatabaseUnavailableError",
    "DuplicateMasterResumeError",
    "JobNotFoundError",
    "JobRepository",
    "MasterResumeNotFoundError",
    "MasterResumeRepository",
    "PersistenceError",
    "ResumeVersionNotFoundError",
    "ResumeVersionRepository",
    "normalized_text_hash",
    "structured_content_hash",
]
