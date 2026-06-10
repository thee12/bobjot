"""FastAPI application factory and local-development entrypoint."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai_internship_assistant.api.dependencies import ApiContainer, build_container
from ai_internship_assistant.api.errors import register_exception_handlers
from ai_internship_assistant.api.routers import (
    applications,
    exports,
    health,
    jobs,
    optimization,
    pipeline,
    resumes,
)


def create_app(container: ApiContainer | None = None) -> FastAPI:
    """Create a testable API application with application-scoped dependencies."""

    app = FastAPI(
        title="AI Internship Application Assistant API",
        version="0.1.0",
        description=(
            "Backend API for resume parsing, job discovery, optimization, export, "
            "and application tracking."
        ),
    )
    app.state.container = container or build_container()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            origin.strip()
            for origin in app.state.container.settings.cors_allowed_origins.split(",")
            if origin.strip()
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    for router in (
        health.router,
        resumes.router,
        jobs.router,
        optimization.router,
        pipeline.router,
        exports.router,
        applications.router,
    ):
        app.include_router(router)
    return app


app = create_app()
