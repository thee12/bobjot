"""Reusable conservative skill normalization and relationship vocabulary."""

import re
from collections.abc import Iterable

_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9+#]+")

SKILL_ALIASES: dict[str, tuple[str, ...]] = {
    "Python": ("Python3", "Python 3"),
    "JavaScript": ("JS", "ECMAScript"),
    "TypeScript": ("TS",),
    "Amazon Web Services": ("AWS",),
    "Google Cloud": ("GCP", "Google Cloud Platform"),
    "Security+": ("CompTIA Security+", "Security Plus", "CompTIA Security Plus"),
    "Network+": ("CompTIA Network+", "Network Plus", "CompTIA Network Plus"),
    "Linux": ("Linux OS", "GNU/Linux"),
    "GitHub": ("Github",),
    "SIEM": ("security information and event management",),
    "MITRE ATT&CK": ("MITRE", "ATT&CK"),
}

RELATED_SKILLS: dict[str, tuple[str, ...]] = {
    "Networking": ("TCP/IP", "DNS", "routing", "switching", "packet analysis"),
    "Packet Sniffer": ("packet analysis", "network traffic analysis"),
    "Wireshark": ("packet analysis", "network traffic analysis"),
    "Linux": ("command line", "shell scripting", "system administration"),
    "Security+": ("security fundamentals", "risk management", "access control", "cryptography"),
}


def normalize_match_term(value: str) -> str:
    """Normalize a skill while preserving punctuation that changes meaning."""

    return _NON_ALPHANUMERIC.sub(" ", value.casefold()).strip()


def canonical_skill_name(value: str) -> str:
    """Return a canonical alias label for comparison, or normalized source text."""

    normalized = normalize_match_term(value)
    for canonical, aliases in SKILL_ALIASES.items():
        if normalized in {
            normalize_match_term(canonical),
            *(normalize_match_term(alias) for alias in aliases),
        }:
            return normalize_match_term(canonical)
    return normalized


def related_job_terms(candidate_skill: str) -> tuple[str, ...]:
    """Return only conservatively related, non-equivalent job terminology."""

    canonical = canonical_skill_name(candidate_skill)
    for source, related in RELATED_SKILLS.items():
        if canonical_skill_name(source) == canonical:
            return related
    return ()


def deduplicate_match_terms(values: Iterable[str]) -> list[str]:
    """Deduplicate terms using alias-aware canonical comparison."""

    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        canonical = canonical_skill_name(value)
        if canonical and canonical not in seen:
            seen.add(canonical)
            result.append(value)
    return result
