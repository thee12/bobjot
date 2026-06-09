"""Stored resume-version export and safe file download endpoints."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import ExportResumeRequest, ExportResumeResponse
from ai_internship_assistant.api.workflow import ApiWorkflowService

router = APIRouter(prefix="/exports", tags=["exports"])


@router.post("/resume-version/{version_id}", response_model=ExportResumeResponse)
def export_resume_version(
    version_id: str,
    request: ExportResumeRequest,
    container: ContainerDependency,
) -> ExportResumeResponse:
    """Export an immutable stored resume version in requested formats."""

    files = ApiWorkflowService(container).export_version(
        version_id,
        request.formats,
        allow_overwrite=request.allow_overwrite,
        options=request.options,
    )
    return ExportResumeResponse(version_id=version_id, exported_files=files)


@router.get("/files/{file_id}", response_class=FileResponse)
def download_export(file_id: str, container: ContainerDependency) -> FileResponse:
    """Download only an export registered under an opaque application file ID."""

    artifact = container.exports.get(file_id)
    if artifact is None or not artifact.path.is_file():
        raise HTTPException(status_code=404, detail="export file was not found")
    allowed = container.export_dir.resolve()
    resolved = artifact.path.resolve()
    if allowed not in resolved.parents:
        raise HTTPException(status_code=404, detail="export file was not found")
    return FileResponse(
        resolved,
        media_type=artifact.media_type,
        filename=artifact.filename,
    )
