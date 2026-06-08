"""Deterministic, source-agnostic job search query generation.

The generator converts a CandidateProfile and optional JobSearchPreferences
into structured, explainable, role-oriented queries. It does not search job
sources, scrape websites, rank postings, or perform ATS analysis.
"""

import re
from collections.abc import Iterable, Sequence

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    CandidateProfile,
    ExperienceLevel,
    JobSearchPreferences,
    JobSearchQuery,
    JobSearchQuerySet,
    QueryPriority,
    RemotePreference,
    SearchEmploymentType,
)

_SENIOR_EXCLUDED_TERMS = [
    "Senior",
    "Staff",
    "Principal",
    "Lead",
    "Manager",
    "Director",
    "Architect",
]

_DOMAIN_ROLE_TIERS: dict[CandidateDomain, dict[QueryPriority, list[str]]] = {
    CandidateDomain.CYBERSECURITY: {
        QueryPriority.HIGH: [
            "Cybersecurity Intern",
            "SOC Analyst Intern",
            "Security Operations Intern",
        ],
        QueryPriority.MEDIUM: [
            "Information Security Intern",
            "Network Security Intern",
            "Cyber Defense Intern",
            "Security Analyst Intern",
        ],
        QueryPriority.LOW: ["IT Support Intern", "Network Operations Intern"],
    },
    CandidateDomain.SOFTWARE_ENGINEERING: {
        QueryPriority.HIGH: ["Software Engineering Intern", "Software Developer Intern"],
        QueryPriority.MEDIUM: [
            "Backend Developer Intern",
            "Full Stack Developer Intern",
            "Python Developer Intern",
        ],
        QueryPriority.LOW: ["Application Development Intern", "Web Development Intern"],
    },
    CandidateDomain.NETWORKING: {
        QueryPriority.HIGH: ["Network Engineering Intern", "Network Operations Intern"],
        QueryPriority.MEDIUM: ["NOC Intern", "Infrastructure Intern", "Systems Intern"],
        QueryPriority.LOW: ["IT Support Intern", "Technical Support Intern"],
    },
    CandidateDomain.IT_SUPPORT: {
        QueryPriority.HIGH: ["IT Intern", "Help Desk Intern", "Technical Support Intern"],
        QueryPriority.MEDIUM: ["Desktop Support Intern", "Systems Intern"],
        QueryPriority.LOW: ["Network Operations Intern"],
    },
    CandidateDomain.CLOUD_ENGINEERING: {
        QueryPriority.HIGH: ["Cloud Engineering Intern", "Cloud Operations Intern"],
        QueryPriority.MEDIUM: [
            "Cloud Security Intern",
            "DevOps Intern",
            "Infrastructure Engineering Intern",
        ],
        QueryPriority.LOW: ["Systems Intern"],
    },
    CandidateDomain.DEVOPS: {
        QueryPriority.HIGH: ["DevOps Intern", "Platform Engineering Intern"],
        QueryPriority.MEDIUM: ["Cloud Engineering Intern", "Infrastructure Engineering Intern"],
        QueryPriority.LOW: ["Systems Intern"],
    },
    CandidateDomain.DATA_SCIENCE: {
        QueryPriority.HIGH: ["Data Science Intern", "Data Analyst Intern"],
        QueryPriority.MEDIUM: ["Analytics Intern", "Business Intelligence Intern"],
        QueryPriority.LOW: ["Software Engineering Intern"],
    },
    CandidateDomain.MACHINE_LEARNING: {
        QueryPriority.HIGH: ["Machine Learning Intern", "AI Engineering Intern"],
        QueryPriority.MEDIUM: ["Data Science Intern", "Applied AI Intern"],
        QueryPriority.LOW: ["Software Engineering Intern"],
    },
    CandidateDomain.WEB_DEVELOPMENT: {
        QueryPriority.HIGH: ["Web Development Intern", "Frontend Development Intern"],
        QueryPriority.MEDIUM: ["Full Stack Developer Intern", "Backend Developer Intern"],
        QueryPriority.LOW: ["Software Engineering Intern"],
    },
    CandidateDomain.SYSTEMS_ADMINISTRATION: {
        QueryPriority.HIGH: ["Systems Administration Intern", "Infrastructure Intern"],
        QueryPriority.MEDIUM: ["IT Operations Intern", "Cloud Operations Intern"],
        QueryPriority.LOW: ["IT Support Intern"],
    },
    CandidateDomain.GENERAL_TECHNOLOGY: {
        QueryPriority.HIGH: ["Technology Intern"],
        QueryPriority.MEDIUM: ["IT Intern"],
        QueryPriority.LOW: ["Entry Level Technology"],
    },
}


class JobSearchQueryGenerationError(TypeError):
    """Raised when query generation receives an invalid programmer input."""


class JobSearchQueryGenerator:
    """Generate structured job-search queries from a CandidateProfile."""

    def generate(
        self,
        candidate_profile: CandidateProfile,
        preferences: JobSearchPreferences | None = None,
    ) -> JobSearchQuerySet:
        """Return a deduplicated JobSearchQuerySet without searching the internet."""

        if not isinstance(candidate_profile, CandidateProfile):
            msg = "candidate_profile must be a CandidateProfile instance"
            raise JobSearchQueryGenerationError(msg)
        if preferences is not None and not isinstance(preferences, JobSearchPreferences):
            msg = "preferences must be a JobSearchPreferences instance"
            raise JobSearchQueryGenerationError(msg)

        resolved_preferences = preferences or JobSearchPreferences()
        role_candidates = self._role_candidates(candidate_profile, resolved_preferences)
        location_variants = self._location_variants(resolved_preferences)
        employment_types = self._employment_types(resolved_preferences)
        excluded_terms = self._excluded_terms(candidate_profile, resolved_preferences)
        excluded_roles = {
            self._normalize_text(role) for role in resolved_preferences.excluded_roles
        }

        queries: list[JobSearchQuery] = []
        seen: set[str] = set()
        for role, priority in role_candidates:
            if self._normalize_text(role) in excluded_roles:
                continue
            if self._contains_excluded_seniority(role, excluded_terms):
                continue

            for location, remote, hybrid in location_variants:
                for employment_type in employment_types:
                    adjusted_role = self._role_for_employment_type(role, employment_type)
                    query_text = self._query_text(adjusted_role, location, remote, hybrid)
                    normalized_query = self._normalize_text(query_text)
                    if normalized_query in seen:
                        continue
                    seen.add(normalized_query)
                    queries.append(
                        JobSearchQuery(
                            query_text=query_text,
                            role=adjusted_role,
                            location=location,
                            employment_type=employment_type,
                            remote=remote,
                            hybrid=hybrid,
                            priority=priority,
                            source_hint=None,
                            reason=self._reason(candidate_profile, role, priority),
                            max_results=resolved_preferences.max_results_per_query,
                        )
                    )

        primary_queries = [query for query in queries if query.priority == QueryPriority.HIGH]
        secondary_queries = [
            query
            for query in queries
            if query.priority in {QueryPriority.MEDIUM, QueryPriority.LOW}
        ]
        return JobSearchQuerySet(
            queries=queries,
            primary_queries=primary_queries,
            secondary_queries=secondary_queries,
            excluded_terms=excluded_terms,
            generated_from_profile=True,
        )

    def _role_candidates(
        self,
        profile: CandidateProfile,
        preferences: JobSearchPreferences,
    ) -> list[tuple[str, QueryPriority]]:
        candidates: list[tuple[str, QueryPriority]] = []
        candidates.extend((role, QueryPriority.HIGH) for role in preferences.desired_roles)
        candidates.extend((role, QueryPriority.HIGH) for role in profile.target_roles)
        candidates.extend(self._domain_roles(profile.primary_domain))

        for domain in profile.secondary_domains:
            candidates.extend(
                (role, self._demote_priority(priority))
                for role, priority in self._domain_roles(domain)
            )

        return self._deduplicate_roles(candidates)

    def _domain_roles(self, domain: CandidateDomain) -> list[tuple[str, QueryPriority]]:
        return [
            (role, priority)
            for priority, roles in _DOMAIN_ROLE_TIERS[domain].items()
            for role in roles
        ]

    def _location_variants(
        self,
        preferences: JobSearchPreferences,
    ) -> list[tuple[str | None, bool, bool]]:
        locations = self._deduplicate_text(preferences.desired_locations)
        variants: list[tuple[str | None, bool, bool]] = []
        remote_preference = preferences.remote_preference

        if remote_preference not in {RemotePreference.REMOTE_ONLY, RemotePreference.HYBRID_ONLY}:
            variants.extend((location, False, False) for location in locations)

        if remote_preference in {RemotePreference.REMOTE_ALLOWED, RemotePreference.REMOTE_ONLY}:
            variants.append((None, True, False))

        if remote_preference in {RemotePreference.HYBRID_ALLOWED, RemotePreference.HYBRID_ONLY}:
            if locations:
                variants.extend((location, False, True) for location in locations)
            else:
                variants.append((None, False, True))

        if not variants:
            variants.append((None, False, False))

        return variants

    def _employment_types(
        self,
        preferences: JobSearchPreferences,
    ) -> list[SearchEmploymentType]:
        if preferences.employment_types:
            return list(dict.fromkeys(preferences.employment_types))
        return [SearchEmploymentType.INTERNSHIP, SearchEmploymentType.ENTRY_LEVEL]

    def _excluded_terms(
        self,
        profile: CandidateProfile,
        preferences: JobSearchPreferences,
    ) -> list[str]:
        excluded = list(preferences.excluded_roles)
        if profile.experience_level in {
            ExperienceLevel.STUDENT,
            ExperienceLevel.INTERNSHIP,
            ExperienceLevel.ENTRY_LEVEL,
            ExperienceLevel.JUNIOR,
        }:
            excluded.extend(_SENIOR_EXCLUDED_TERMS)
        excluded.extend(f"company:{company}" for company in preferences.excluded_companies)
        return self._deduplicate_text(excluded)

    def _role_for_employment_type(
        self,
        role: str,
        employment_type: SearchEmploymentType,
    ) -> str:
        if employment_type == SearchEmploymentType.INTERNSHIP:
            return role if "intern" in role.casefold() else f"{role} Intern"
        if employment_type == SearchEmploymentType.ENTRY_LEVEL:
            without_intern = re.sub(r"\s+intern(ship)?\b", "", role, flags=re.IGNORECASE).strip()
            if "entry level" in without_intern.casefold():
                return without_intern
            return f"Entry Level {without_intern}"
        return re.sub(r"\s+intern(ship)?\b", "", role, flags=re.IGNORECASE).strip()

    def _query_text(
        self,
        role: str,
        location: str | None,
        remote: bool,
        hybrid: bool,
    ) -> str:
        parts = [role]
        if location:
            parts.append(self._display_location(location))
        if remote:
            parts.append("Remote")
        if hybrid:
            parts.append("Hybrid")
        return " ".join(parts)

    def _reason(
        self,
        profile: CandidateProfile,
        role: str,
        priority: QueryPriority,
    ) -> str:
        evidence = profile.core_skills[:3] + profile.certifications[:2]
        evidence_text = ", ".join(evidence) if evidence else profile.primary_domain.value
        return (
            f"Generated as a {priority.value}-priority {role} search because the candidate "
            f"profile indicates {profile.primary_domain.value} alignment supported by "
            f"{evidence_text}."
        )

    def _contains_excluded_seniority(self, role: str, excluded_terms: Sequence[str]) -> bool:
        normalized_role = self._normalize_text(role)
        return any(
            self._normalize_text(term) in normalized_role
            for term in excluded_terms
            if not term.casefold().startswith("company:")
        )

    def _demote_priority(self, priority: QueryPriority) -> QueryPriority:
        if priority == QueryPriority.HIGH:
            return QueryPriority.MEDIUM
        return QueryPriority.LOW

    def _deduplicate_roles(
        self,
        candidates: Iterable[tuple[str, QueryPriority]],
    ) -> list[tuple[str, QueryPriority]]:
        priorities = {
            QueryPriority.HIGH: 0,
            QueryPriority.MEDIUM: 1,
            QueryPriority.LOW: 2,
        }
        result: dict[str, tuple[str, QueryPriority]] = {}
        for role, priority in candidates:
            normalized = self._normalize_text(role)
            existing = result.get(normalized)
            if existing is None or priorities[priority] < priorities[existing[1]]:
                result[normalized] = (role.strip(), priority)
        return list(result.values())

    def _deduplicate_text(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_text(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(value.strip())
        return result

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

    def _display_location(self, location: str) -> str:
        return re.sub(r"\s*,\s*", " ", location.strip())
