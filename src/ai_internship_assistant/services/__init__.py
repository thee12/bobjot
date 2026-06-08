"""Service-layer entrypoints for application workflows."""

from ai_internship_assistant.services.document_extraction import (
    DocumentTextExtractor,
    UnsupportedDocumentFormatError,
    extract_text,
)

__all__ = [
    "DocumentTextExtractor",
    "UnsupportedDocumentFormatError",
    "extract_text",
]

