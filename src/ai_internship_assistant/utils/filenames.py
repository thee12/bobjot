"""Safe deterministic filename utilities for generated resume artifacts."""

import re
from pathlib import Path

_UNSAFE_FILENAME = re.compile(r"[^a-z0-9]+")
_REPEATED_UNDERSCORE = re.compile(r"_+")


def sanitize_filename(value: str, *, max_length: int = 180) -> str:
    """Return a lowercase filesystem-safe filename while preserving its extension."""

    source = Path(value)
    suffix = source.suffix.casefold()
    stem = _UNSAFE_FILENAME.sub("_", source.stem.casefold())
    stem = _REPEATED_UNDERSCORE.sub("_", stem).strip("_") or "resume"
    available = max(1, max_length - len(suffix))
    return f"{stem[:available].rstrip('_')}{suffix}"


def generate_resume_filename(
    candidate_name: str | None,
    target_job_title: str | None = None,
    target_company: str | None = None,
) -> str:
    """Generate a readable safe Markdown filename from existing resume metadata."""

    parts = [
        candidate_name or "candidate",
        target_job_title or "resume",
        *(value for value in [target_company] if value),
        "resume",
    ]
    return sanitize_filename("_".join(parts) + ".md")
