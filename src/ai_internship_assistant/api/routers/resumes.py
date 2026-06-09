"""Resume upload and stored resume endpoints."""

import hashlib
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import (
    ResumeDetailResponse,
    ResumeSummaryResponse,
    ResumeUploadResponse,
    ResumeVersionDetailResponse,
)
from ai_internship_assistant.api.workflow import ApiWorkflowService
from ai_internship_assistant.domain.models import ResumeSourceFileMetadata, ResumeVersionSummary
from ai_internship_assistant.services import DocumentTextExtractor
from ai_internship_assistant.utils.filenames import sanitize_filename

router = APIRouter(prefix="/resumes", tags=["resumes"])
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
_ALLOWED_SUFFIXES = {".pdf", ".docx"}


@router.post("/upload", response_model=ResumeUploadResponse, status_code=201)
async def upload_resume(
    container: ContainerDependency,
    file: Annotated[UploadFile, File()],
    parse_with_llm: Annotated[bool, Form()] = True,
) -> ResumeUploadResponse:
    """Extract, parse, validate, profile, and persist one resume upload."""

    filename = sanitize_filename(file.filename or "resume")
    suffix = Path(filename).suffix.casefold()
    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(status_code=415, detail="only PDF and DOCX resumes are supported")
    content = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="resume upload exceeds 10 MB")
    if not _matches_signature(content, suffix):
        raise HTTPException(
            status_code=415,
            detail="resume file signature does not match extension",
        )
    if not parse_with_llm:
        raise HTTPException(status_code=400, detail="non-LLM resume parsing is not configured")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temporary:
            temporary.write(content)
            temporary_path = Path(temporary.name)
        text = DocumentTextExtractor().extract_text(temporary_path)
        resume = container.resume_parser.parse(text)
        generated = container.profile_pipeline.run(resume)
        metadata = ResumeSourceFileMetadata(
            original_filename=filename,
            file_type=suffix.removeprefix("."),
            file_size_bytes=len(content),
            content_hash=hashlib.sha256(content).hexdigest(),
        )
        stored = container.versioning.save_master_resume(resume, metadata, source_text=text)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    warnings = [issue.message for issue in generated.validation_report.issues]
    return ResumeUploadResponse(
        resume_id=stored.id,
        candidate_name=stored.candidate_name,
        validation_warnings=warnings,
        candidate_profile_summary=generated.profile.profile_summary,
        created_at=stored.created_at,
    )


@router.get("", response_model=list[ResumeSummaryResponse])
def list_resumes(container: ContainerDependency) -> list[ResumeSummaryResponse]:
    """List stored master resume summaries."""

    return [
        ResumeSummaryResponse(
            resume_id=item.id,
            candidate_name=item.candidate_name,
            original_filename=item.original_filename,
            created_at=item.created_at,
            updated_at=item.updated_at,
            version_count=len(container.versions.list_for_master(item.id)),
        )
        for item in container.versioning.list_master_resumes()
    ]


@router.get("/versions/{version_id}", response_model=ResumeVersionDetailResponse)
def get_resume_version(
    version_id: str,
    container: ContainerDependency,
) -> ResumeVersionDetailResponse:
    """Return one optimized resume version detail."""

    item = container.versioning.get_resume_version(version_id)
    return ResumeVersionDetailResponse(
        version_id=item.id,
        optimized_resume=item.optimized_resume,
        target_job_id=item.target_job_id,
        target_job_title=item.target_job_title,
        target_company=item.target_company,
        before_ats_score=item.before_ats_score,
        estimated_after_score_low=item.estimated_after_score_low,
        estimated_after_score_high=item.estimated_after_score_high,
        change_log=item.change_log,
        safety_report=item.safety_report,
        created_at=item.created_at,
    )


@router.get("/{resume_id}/versions")
def list_resume_versions(
    resume_id: str,
    container: ContainerDependency,
) -> list[ResumeVersionSummary]:
    """List optimized resume version summaries."""

    return container.versioning.get_version_summaries(resume_id)


@router.get("/{resume_id}", response_model=ResumeDetailResponse)
def get_resume(resume_id: str, container: ContainerDependency) -> ResumeDetailResponse:
    """Return stored resume detail with regenerated profile and validation."""

    stored = container.versioning.get_master_resume(resume_id)
    generated = ApiWorkflowService(container).profile_for_resume(stored)
    return ResumeDetailResponse(
        resume_id=stored.id,
        candidate_name=stored.candidate_name,
        parsed_resume=stored.parsed_resume,
        candidate_profile=generated.profile,
        validation_report=generated.validation_report,
        created_at=stored.created_at,
    )


def _matches_signature(content: bytes, suffix: str) -> bool:
    if suffix == ".pdf":
        return content.startswith(b"%PDF")
    return content.startswith(b"PK")
