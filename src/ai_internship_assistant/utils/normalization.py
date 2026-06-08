"""Normalization helpers used for comparison without mutating source models."""

import re

_CANONICAL_SKILL_NAMES = {
    "github": "GitHub",
    "python": "Python",
    "python3": "Python",
    "python 3": "Python",
}

_WHITESPACE_PATTERN = re.compile(r"\s+")


def normalize_skill_name(name: str) -> str:
    """Return a canonical skill name for internal comparisons.

    The original Resume is never modified. This helper is intentionally small
    and reusable so future modules can share comparison behavior without
    overwriting candidate-provided wording.
    """

    normalized = _WHITESPACE_PATTERN.sub(" ", name.strip()).casefold()
    normalized = normalized.replace("python 3", "python3")
    canonical = _CANONICAL_SKILL_NAMES.get(normalized)
    if canonical is not None:
        return canonical
    return normalized

