"""Health and dependency readiness endpoints."""

from fastapi import APIRouter
from sqlalchemy import text

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import DependencyHealthResponse, HealthResponse
from ai_internship_assistant.storage import DatabaseUnavailableError

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return lightweight process health."""

    return HealthResponse()


@router.get("/dependencies", response_model=DependencyHealthResponse)
def dependency_health(container: ContainerDependency) -> DependencyHealthResponse:
    """Check local dependencies without network or LLM calls."""

    database_status = "ok"
    try:
        with container.database.session() as session:
            session.execute(text("SELECT 1"))
    except DatabaseUnavailableError:
        database_status = "unavailable"
    writable = container.export_dir.exists() and container.export_dir.is_dir()
    status = "ok" if database_status == "ok" and writable else "degraded"
    return DependencyHealthResponse(
        status=status,
        database=database_status,
        llm_enabled=container.settings.enable_llm_analysis,
        export_directory=container.export_dir.name,
        export_directory_writable=writable,
    )
