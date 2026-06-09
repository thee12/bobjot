"""Centralized API exception-to-HTTP mapping."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ai_internship_assistant.api.dependencies import ResumeParserUnavailableError
from ai_internship_assistant.services import (
    FullResumeOptimizationError,
    ResumeOptimizationPlanningError,
    ResumeOutputWriteError,
    ResumeParsingError,
    UnsupportedDocumentFormatError,
    UnsupportedResumeFormatError,
)
from ai_internship_assistant.storage import (
    ApplicationNotFoundError,
    CorruptedArtifactError,
    DatabaseUnavailableError,
    JobNotFoundError,
    MasterResumeNotFoundError,
    ResumeVersionNotFoundError,
    SavedJobNotFoundError,
)

_NOT_FOUND = (
    ApplicationNotFoundError,
    JobNotFoundError,
    MasterResumeNotFoundError,
    ResumeVersionNotFoundError,
    SavedJobNotFoundError,
)
_BAD_REQUEST = (
    FullResumeOptimizationError,
    ResumeOptimizationPlanningError,
    UnsupportedDocumentFormatError,
    UnsupportedResumeFormatError,
)


def register_exception_handlers(app: FastAPI) -> None:
    """Register safe domain error responses without raw tracebacks."""

    @app.exception_handler(Exception)
    async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
        if isinstance(exc, _NOT_FOUND):
            return JSONResponse(status_code=404, content={"detail": str(exc)})
        if isinstance(exc, _BAD_REQUEST):
            return JSONResponse(status_code=400, content={"detail": str(exc)})
        if isinstance(exc, (ResumeParsingError, ResumeParserUnavailableError)):
            return JSONResponse(status_code=503, content={"detail": str(exc)})
        if isinstance(exc, DatabaseUnavailableError):
            return JSONResponse(status_code=503, content={"detail": "database unavailable"})
        if isinstance(exc, CorruptedArtifactError):
            return JSONResponse(status_code=500, content={"detail": str(exc)})
        if isinstance(exc, ResumeOutputWriteError):
            return JSONResponse(status_code=500, content={"detail": "resume export failed"})
        return JSONResponse(status_code=500, content={"detail": "internal server error"})
