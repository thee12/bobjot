"""Shared value objects used by multiple domain models."""

from enum import StrEnum

from pydantic import BaseModel, Field


class FileFormat(StrEnum):
    """Supported source document formats."""

    PDF = "pdf"
    DOCX = "docx"


class SourceFile(BaseModel):
    """Metadata for a user-provided or generated document."""

    filename: str = Field(description="Original or generated file name.")
    content_type: str | None = Field(default=None, description="MIME type when available.")
    file_format: FileFormat = Field(description="Normalized document format.")
    sha256: str | None = Field(default=None, description="Optional content hash for deduplication.")

