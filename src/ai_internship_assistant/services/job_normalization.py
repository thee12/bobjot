"""Deterministic, non-mutating job normalization and conservative deduplication."""

import hashlib
import re
from collections.abc import Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ai_internship_assistant.domain.models import (
    EmploymentType,
    JobDeduplicationGroup,
    JobDeduplicationResult,
    JobPosting,
    JobSourceType,
    NormalizedJobPosting,
    WorkArrangement,
)
from ai_internship_assistant.services.job_source_utils import plain_text_from_html

_TRACKING_PARAMETERS = {
    "gh_src",
    "lever-source",
    "lever_source",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}

_COMPANY_ALIASES = {
    "cisco": "cisco",
    "cisco systems": "cisco",
    "cisco systems inc": "cisco",
    "google inc": "google",
    "microsoft corporation": "microsoft",
}

_STATE_ALIASES = {
    "north carolina": "nc",
    "california": "ca",
    "new york": "ny",
    "texas": "tx",
    "washington": "wa",
}

_DIRECT_ATS_SOURCES = {JobSourceType.GREENHOUSE, JobSourceType.LEVER}
_TITLE_NOISE = {
    "summer",
    "spring",
    "fall",
    "winter",
    "2025",
    "2026",
    "2027",
    "2028",
}


class JobNormalizationService:
    """Create normalized job views without changing original postings."""

    def normalize(self, job: JobPosting) -> NormalizedJobPosting:
        """Return a normalized representation suitable for comparison."""

        title = self._normalize_title(self._text(job, "title"))
        company = self._normalize_company(self._text(job, "company"))
        location = self._normalize_location(self._text(job, "location"))
        apply_url = self._normalize_url(self._text(job, "apply_url"))
        source_url = self._normalize_url(self._text(job, "source_url"))
        description = self._normalize_description(self._text(job, "description"))
        employment_type = self._enum_or_default(
            getattr(job, "employment_type", None),
            EmploymentType,
            EmploymentType.UNKNOWN,
        )
        work_arrangement = self._enum_or_default(
            getattr(job, "work_arrangement", None),
            WorkArrangement,
            WorkArrangement.UNKNOWN,
        )
        fingerprint_input = "|".join([company, title, location])
        fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()
        similarity_keys = [
            value
            for value in (
                f"apply:{apply_url}" if apply_url else "",
                f"source:{source_url}" if source_url else "",
                f"identity:{company}|{title}|{location}" if company and title else "",
                f"company-title:{company}|{title}" if company and title else "",
            )
            if value
        ]

        return NormalizedJobPosting(
            original_job=job,
            normalized_title=title,
            normalized_company=company,
            normalized_location=location,
            normalized_employment_type=employment_type,
            normalized_work_arrangement=work_arrangement,
            normalized_apply_url=apply_url,
            normalized_source_url=source_url,
            normalized_description_text=description,
            fingerprint=fingerprint,
            similarity_keys=similarity_keys,
        )

    def normalize_many(self, jobs: Sequence[JobPosting]) -> list[NormalizedJobPosting]:
        """Normalize multiple jobs while preserving source order."""

        return [self.normalize(job) for job in jobs]

    def _normalize_title(self, value: str) -> str:
        normalized = JobPosting._normalize_identity_text(value)
        replacements = (
            (r"\bsoftware engineer\b", "software engineering"),
            (r"\bsoftware developer\b", "software engineering"),
            (r"\binternship\b", "intern"),
            (r"\bco op\b", "intern"),
            (r"\bcoop\b", "intern"),
        )
        for pattern, replacement in replacements:
            normalized = re.sub(pattern, replacement, normalized)
        tokens = [token for token in normalized.split() if token not in _TITLE_NOISE]
        return " ".join(dict.fromkeys(tokens))

    def _normalize_company(self, value: str) -> str:
        normalized = JobPosting._normalize_identity_text(value)
        suffixes = {
            "inc",
            "incorporated",
            "corp",
            "corporation",
            "llc",
            "ltd",
            "limited",
            "systems",
        }
        without_suffixes = " ".join(token for token in normalized.split() if token not in suffixes)
        return _COMPANY_ALIASES.get(
            normalized,
            _COMPANY_ALIASES.get(without_suffixes, without_suffixes),
        )

    def _normalize_location(self, value: str) -> str:
        normalized = JobPosting._normalize_identity_text(value)
        if "remote" in normalized:
            return "remote"
        normalized = normalized.replace("united states", "").strip()
        for full_name, abbreviation in _STATE_ALIASES.items():
            normalized = normalized.replace(full_name, abbreviation)
        tokens = normalized.split()
        return " ".join(dict.fromkeys(tokens))

    def _normalize_url(self, value: str) -> str | None:
        if not value:
            return None
        try:
            parts = urlsplit(value)
        except ValueError:
            return value.strip()
        if not parts.scheme or not parts.netloc:
            return value.strip()
        query = [
            (key, item)
            for key, item in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in _TRACKING_PARAMETERS
        ]
        return urlunsplit(
            (
                parts.scheme.casefold(),
                parts.netloc.casefold(),
                parts.path.rstrip("/") or "/",
                urlencode(sorted(query)),
                "",
            )
        )

    def _normalize_description(self, value: str) -> str:
        return plain_text_from_html(value)

    def _text(self, job: JobPosting, field_name: str) -> str:
        value = getattr(job, field_name, None)
        return str(value).strip() if value is not None else ""

    def _enum_or_default[T](
        self,
        value: object,
        enum_type: type[T],
        default: T,
    ) -> T:
        return value if isinstance(value, enum_type) else default


class JobDeduplicationService:
    """Conservatively group obvious duplicate jobs while preserving originals."""

    def __init__(self, normalizer: JobNormalizationService | None = None) -> None:
        self._normalizer = normalizer or JobNormalizationService()

    def deduplicate(self, jobs: Sequence[JobPosting]) -> JobDeduplicationResult:
        """Return unique jobs, duplicate groups, and possible-duplicate warnings."""

        if not jobs:
            return JobDeduplicationResult(original_count=0)

        normalized = self._normalizer.normalize_many(jobs)
        groups: list[list[NormalizedJobPosting]] = []
        group_matches: list[list[tuple[float, str]]] = []
        warnings: list[str] = []

        for candidate in normalized:
            best_group_index: int | None = None
            best_confidence = 0.0
            best_reason = ""
            warning: str | None = None

            for index, group in enumerate(groups):
                confidence, reason = self._duplicate_confidence(candidate, group[0])
                if confidence > best_confidence:
                    best_group_index = index
                    best_confidence = confidence
                    best_reason = reason
                if 0.70 <= confidence < 0.75:
                    warning = (
                        f"Possible duplicate retained: {self._label(candidate)} and "
                        f"{self._label(group[0])} ({reason})."
                    )

            if best_group_index is not None and best_confidence >= 0.75:
                groups[best_group_index].append(candidate)
                group_matches[best_group_index].append((best_confidence, best_reason))
            else:
                groups.append([candidate])
                group_matches.append([])
                if warning:
                    warnings.append(warning)

        unique_jobs: list[JobPosting] = []
        duplicate_groups: list[JobDeduplicationGroup] = []
        for group, matches in zip(groups, group_matches, strict=True):
            canonical = max(group, key=self._canonical_score)
            unique_jobs.append(canonical.original_job)
            if len(group) > 1:
                duplicates = [job.original_job for job in group if job is not canonical]
                confidence, reason = max(matches, key=lambda item: item[0])
                duplicate_groups.append(
                    JobDeduplicationGroup(
                        canonical_job=canonical.original_job,
                        duplicate_jobs=duplicates,
                        confidence_score=confidence,
                        reason=reason,
                    )
                )

        return JobDeduplicationResult(
            unique_jobs=unique_jobs,
            duplicate_groups=duplicate_groups,
            original_count=len(jobs),
            warnings=warnings,
        )

    def _duplicate_confidence(
        self,
        first: NormalizedJobPosting,
        second: NormalizedJobPosting,
    ) -> tuple[float, str]:
        if first.normalized_apply_url and first.normalized_apply_url == second.normalized_apply_url:
            return 1.0, "identical normalized apply URL"
        if (
            first.normalized_source_url
            and first.normalized_source_url == second.normalized_source_url
        ):
            return 0.95, "identical normalized source URL"
        if not first.normalized_company or first.normalized_company != second.normalized_company:
            return 0.0, "different companies"

        title_similarity = self._token_similarity(first.normalized_title, second.normalized_title)
        locations_equal = (
            bool(first.normalized_location)
            and first.normalized_location == second.normalized_location
        )
        location_unknown = not first.normalized_location or not second.normalized_location

        if title_similarity >= 0.8 and locations_equal:
            return 0.85, "same company, highly similar title, and same location"
        if title_similarity >= 0.8 and location_unknown:
            return 0.70, "same company and similar title with unknown location"
        return 0.0, "insufficient identity similarity"

    def _token_similarity(self, first: str, second: str) -> float:
        first_tokens = set(first.split())
        second_tokens = set(second.split())
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    def _canonical_score(self, job: NormalizedJobPosting) -> tuple[int, int, int, int, int]:
        original = job.original_job
        description_length = len(job.normalized_description_text)
        has_apply_url = int(bool(job.normalized_apply_url))
        is_direct_ats = int(getattr(original, "source", None) in _DIRECT_ATS_SOURCES)
        has_posted_date = int(bool(getattr(original, "posted_date", None)))
        structured_count = sum(
            len(self._sequence(original, field_name))
            for field_name in (
                "responsibilities",
                "requirements",
                "preferred_qualifications",
                "technologies",
                "certifications",
            )
        )
        return (
            description_length,
            has_apply_url,
            is_direct_ats,
            has_posted_date,
            structured_count,
        )

    def _sequence(self, job: JobPosting, field_name: str) -> Sequence[object]:
        value = getattr(job, field_name, None)
        return value if isinstance(value, Sequence) and not isinstance(value, str) else []

    def _label(self, job: NormalizedJobPosting) -> str:
        company = job.normalized_company or "<missing company>"
        title = job.normalized_title or "<missing title>"
        return f"{company} / {title}"
