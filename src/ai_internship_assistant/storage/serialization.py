"""Consistent, versioned Pydantic JSON serialization for persisted artifacts."""

import hashlib
import json
import re

from pydantic import BaseModel, ValidationError

_MODEL_SCHEMA_VERSION = "1"
_WHITESPACE = re.compile(r"\s+")


class ArtifactSerializationError(ValueError):
    """Raised when a persisted artifact cannot be serialized or reconstructed."""


def serialize_model(model: BaseModel) -> str:
    """Serialize one Pydantic model consistently without logging its contents."""

    try:
        return model.model_dump_json()
    except (TypeError, ValueError) as exc:
        raise ArtifactSerializationError("artifact serialization failed") from exc


def deserialize_model[ModelT: BaseModel](payload: str, model_type: type[ModelT]) -> ModelT:
    """Reconstruct one Pydantic model from persisted JSON."""

    try:
        return model_type.model_validate_json(payload)
    except (ValidationError, ValueError) as exc:
        raise ArtifactSerializationError(
            f"stored {model_type.__name__} data is corrupted or incompatible"
        ) from exc


def serialize_models(models: list[BaseModel]) -> str:
    """Serialize a list of Pydantic models as one stable JSON array."""

    return json.dumps([model.model_dump(mode="json") for model in models], sort_keys=True)


def deserialize_models[ModelT: BaseModel](
    payload: str,
    model_type: type[ModelT],
) -> list[ModelT]:
    """Reconstruct a list of Pydantic models from persisted JSON."""

    try:
        values = json.loads(payload)
        if not isinstance(values, list):
            raise ValueError
        return [model_type.model_validate(value) for value in values]
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
        raise ArtifactSerializationError(
            f"stored {model_type.__name__} list is corrupted or incompatible"
        ) from exc


def structured_content_hash(model: BaseModel) -> str:
    """Return a deterministic SHA-256 hash for a structured artifact."""

    payload = json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def normalized_text_hash(value: str) -> str:
    """Return a deterministic SHA-256 hash after conservative whitespace normalization."""

    normalized = _WHITESPACE.sub(" ", value).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def model_schema_version() -> str:
    """Return the current persisted-model schema version."""

    return _MODEL_SCHEMA_VERSION


def compatibility_warnings(stored_version: str) -> list[str]:
    """Return a warning when an artifact uses a different model schema version."""

    if stored_version == _MODEL_SCHEMA_VERSION:
        return []
    return [
        f"artifact schema version {stored_version} differs from current "
        f"version {_MODEL_SCHEMA_VERSION}"
    ]
