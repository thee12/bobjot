"""Shared CLI dependency construction, validation, and output helpers."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, ValidationError

from ai_internship_assistant.config import AppSettings
from ai_internship_assistant.services import ApplicationTrackingService
from ai_internship_assistant.storage import (
    ApplicationRepository,
    Database,
    SavedJobRepository,
)
from ai_internship_assistant.storage.repositories import ResumeVersionRepository


class CliInputError(ValueError):
    """Raised for invalid user-provided CLI input."""


@dataclass(frozen=True)
class CliContext:
    """Dependencies shared by every CLI command."""

    tracking: ApplicationTrackingService


def resolve_database_url(cli_value: str | None) -> str:
    """Resolve CLI, JOBBOT, then application settings database configuration."""

    return cli_value or os.getenv("JOBBOT_DATABASE_URL") or AppSettings().database_url


def build_context(database_url: str) -> CliContext:
    """Initialize the configured database and construct tracker services."""

    _create_sqlite_parent(database_url)
    database = Database(database_url)
    database.initialize()
    versions = ResumeVersionRepository(database)
    return CliContext(
        tracking=ApplicationTrackingService(
            SavedJobRepository(database),
            ApplicationRepository(database),
            versions,
        )
    )


def load_json_model[ModelT: BaseModel](path: Path, model_type: type[ModelT]) -> ModelT:
    """Load and validate a Pydantic model from a user-provided JSON file."""

    if not path.is_file():
        raise CliInputError(f"JSON file not found: {path}")
    try:
        return model_type.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CliInputError(f"JSON file could not be read: {path}") from exc
    except ValidationError as exc:
        message = exc.errors()[0]["msg"]
        raise CliInputError(f"Invalid {model_type.__name__} JSON: {message}") from exc


def parse_enum[EnumT](value: str, enum_type: type[EnumT], label: str) -> EnumT:
    """Parse case-insensitive CLI enum input."""

    try:
        return enum_type(value.strip().casefold())  # type: ignore[call-arg]
    except ValueError as exc:
        choices = ", ".join(item.value.upper() for item in enum_type)  # type: ignore[attr-defined]
        raise CliInputError(f"Invalid {label}: {value}. Choose one of: {choices}") from exc


def json_echo(value: BaseModel | dict[str, Any] | list[Any]) -> None:
    """Print valid JSON with Pydantic-native dates and enum serialization."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def preview(value: str | None, length: int = 60) -> str:
    """Return one compact single-line CLI preview."""

    if not value:
        return "-"
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= length else f"{cleaned[: length - 3]}..."


def fail(message: str) -> None:
    """Print one clear expected user error without a traceback."""

    typer.echo(f"Error: {message}", err=True)
    raise typer.Exit(code=1)


def _create_sqlite_parent(database_url: str) -> None:
    if not database_url.startswith("sqlite:///") or database_url == "sqlite:///:memory:":
        return
    path = Path(database_url.removeprefix("sqlite:///"))
    path.parent.mkdir(parents=True, exist_ok=True)
