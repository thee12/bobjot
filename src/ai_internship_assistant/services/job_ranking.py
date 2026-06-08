"""Deterministic, explainable candidate/job fit scoring and ranking."""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from ai_internship_assistant.domain.models import (
    CandidateDomain,
    CandidateProfile,
    EmploymentType,
    ExperienceLevel,
    JobFitScore,
    JobPosting,
    JobSearchPreferences,
    RankedJobResult,
    RankedJobResultSet,
    RecommendationLevel,
    RemotePreference,
    SearchEmploymentType,
    WorkArrangement,
)
from ai_internship_assistant.services.job_source_utils import (
    has_senior_title,
    plain_text_from_html,
)
from ai_internship_assistant.utils import normalize_skill_name

_SCORING_VERSION = "rule-based-v1"

_DOMAIN_KEYWORDS: dict[CandidateDomain, set[str]] = {
    CandidateDomain.CYBERSECURITY: {
        "cybersecurity",
        "security",
        "soc",
        "incident response",
        "vulnerability",
        "threat detection",
        "network security",
        "endpoint security",
        "risk assessment",
        "access control",
        "iam",
        "mitre att ck",
    },
    CandidateDomain.SOFTWARE_ENGINEERING: {
        "software",
        "developer",
        "backend",
        "frontend",
        "api",
        "python",
        "java",
        "javascript",
    },
    CandidateDomain.NETWORKING: {
        "network",
        "networking",
        "tcp ip",
        "dns",
        "dhcp",
        "routing",
        "switching",
        "firewall",
        "packet analysis",
    },
    CandidateDomain.CLOUD_ENGINEERING: {"cloud", "aws", "azure", "gcp", "terraform"},
    CandidateDomain.DEVOPS: {"devops", "ci cd", "docker", "kubernetes", "jenkins"},
    CandidateDomain.DATA_SCIENCE: {"data science", "analytics", "pandas", "tableau", "statistics"},
    CandidateDomain.MACHINE_LEARNING: {"machine learning", "pytorch", "tensorflow", "model"},
    CandidateDomain.IT_SUPPORT: {"it support", "help desk", "troubleshooting", "desktop support"},
    CandidateDomain.SYSTEMS_ADMINISTRATION: {
        "systems administration",
        "active directory",
        "windows server",
        "linux administration",
    },
    CandidateDomain.WEB_DEVELOPMENT: {"web", "react", "javascript", "html", "css", "node js"},
    CandidateDomain.GENERAL_TECHNOLOGY: set(),
}

_KEYWORDS = {
    "siem",
    "soc",
    "incident response",
    "vulnerability management",
    "threat detection",
    "log analysis",
    "network security",
    "endpoint security",
    "risk assessment",
    "access control",
    "iam",
    "mitre att ck",
    "python",
    "java",
    "javascript",
    "sql",
    "api",
    "backend",
    "frontend",
    "cloud",
    "git",
    "linux",
    "tcp ip",
    "dns",
    "dhcp",
    "routing",
    "switching",
    "firewall",
    "packet analysis",
}

_CLEARANCE_PATTERN = re.compile(r"\b(?:security\s+)?clearance\b|\bsecret\b|\btop secret\b", re.I)
_MASTERS_PATTERN = re.compile(r"\bmaster'?s\b|\bm\.?s\.?\b", re.I)
_YEARS_PATTERN = re.compile(r"\b(?:5|[6-9]|\d{2,})\+?\s+years?\b", re.I)
_EARLY_CAREER_PATTERN = re.compile(
    r"\bintern(?:ship)?\b|\bco-?op\b|\bnew grad\b|\bentry[- ]level\b|"
    r"\bearly career\b|\buniversity program\b",
    re.I,
)


@dataclass(frozen=True, slots=True)
class JobFitScoringConfig:
    """Centralized weights, recommendation thresholds, and penalties."""

    role_weight: float = 0.25
    skill_weight: float = 0.25
    domain_weight: float = 0.15
    experience_level_weight: float = 0.15
    employment_type_weight: float = 0.10
    location_weight: float = 0.03
    certification_weight: float = 0.05
    keyword_weight: float = 0.02
    flag_penalties: dict[str, float] = field(
        default_factory=lambda: {
            "senior_level_role": 30.0,
            "requires_clearance": 8.0,
            "requires_masters_degree": 8.0,
            "requires_5_plus_years": 20.0,
            "unrelated_domain": 10.0,
            "non_internship_role": 8.0,
            "location_mismatch": 8.0,
        }
    )
    strong_match_min: float = 90.0
    good_match_min: float = 75.0
    possible_match_min: float = 60.0
    weak_match_min: float = 40.0

    def __post_init__(self) -> None:
        total = (
            self.role_weight
            + self.skill_weight
            + self.domain_weight
            + self.experience_level_weight
            + self.employment_type_weight
            + self.location_weight
            + self.certification_weight
            + self.keyword_weight
        )
        if abs(total - 1.0) > 0.0001:
            msg = f"scoring weights must total 1.0, got {total}"
            raise ValueError(msg)


class JobFitScoringService:
    """Score and rank jobs using transparent deterministic rules."""

    def __init__(self, config: JobFitScoringConfig | None = None) -> None:
        self._config = config or JobFitScoringConfig()

    def score_job(
        self,
        candidate_profile: CandidateProfile,
        job: JobPosting,
        preferences: JobSearchPreferences | None = None,
    ) -> JobFitScore:
        """Return an explainable fit score without mutating inputs."""

        text = self._job_text(job)
        role_score = self._role_match(candidate_profile, job)
        matched_skills, missing_skills, skill_score = self._skill_match(
            candidate_profile,
            job,
            text,
        )
        domain_score = self._domain_match(candidate_profile, text)
        experience_score = self._experience_match(candidate_profile, job, text)
        employment_score = self._employment_match(candidate_profile, job, preferences, text)
        location_score, location_mismatch = self._location_match(job, preferences)
        matched_certifications, certification_score = self._certification_match(
            candidate_profile,
            job,
            text,
        )
        matched_keywords, keyword_score = self._keyword_match(candidate_profile, text)
        flags = self._disqualifying_flags(
            candidate_profile,
            job,
            text,
            domain_score,
            location_mismatch,
        )
        warnings = self._warnings(job, missing_skills, flags)

        weighted_score = (
            role_score * self._config.role_weight
            + skill_score * self._config.skill_weight
            + domain_score * self._config.domain_weight
            + experience_score * self._config.experience_level_weight
            + employment_score * self._config.employment_type_weight
            + location_score * self._config.location_weight
            + certification_score * self._config.certification_weight
            + keyword_score * self._config.keyword_weight
        )
        penalty = sum(self._config.flag_penalties.get(flag, 0.0) for flag in flags)
        overall_score = round(min(max(weighted_score - penalty, 0.0), 100.0), 1)

        return JobFitScore(
            overall_score=overall_score,
            role_match_score=round(role_score, 1),
            skill_match_score=round(skill_score, 1),
            domain_match_score=round(domain_score, 1),
            experience_level_score=round(experience_score, 1),
            location_score=round(location_score, 1),
            employment_type_score=round(employment_score, 1),
            certification_match_score=round(certification_score, 1),
            keyword_match_score=round(keyword_score, 1),
            missing_skills=missing_skills,
            matched_skills=matched_skills,
            matched_certifications=matched_certifications,
            matched_keywords=matched_keywords,
            disqualifying_flags=flags,
            warnings=warnings,
            explanation=self._explanation(
                candidate_profile,
                job,
                matched_skills,
                missing_skills,
                matched_certifications,
                flags,
            ),
        )

    def rank_jobs(
        self,
        candidate_profile: CandidateProfile,
        jobs: Sequence[JobPosting],
        preferences: JobSearchPreferences | None = None,
    ) -> RankedJobResultSet:
        """Score jobs and sort them deterministically."""

        scored = [(job, self.score_job(candidate_profile, job, preferences)) for job in jobs]
        scored.sort(key=self._sort_key)
        results = [
            RankedJobResult(
                job=job,
                score=score,
                rank=index,
                recommendation_level=self.recommendation_level(score.overall_score),
            )
            for index, (job, score) in enumerate(scored, start=1)
        ]
        strong_or_good = sum(
            result.recommendation_level
            in {RecommendationLevel.STRONG_MATCH, RecommendationLevel.GOOD_MATCH}
            for result in results
        )
        return RankedJobResultSet(
            results=results,
            scoring_version=_SCORING_VERSION,
            summary=f"Ranked {len(results)} jobs; {strong_or_good} are strong or good matches.",
        )

    def recommendation_level(self, score: float) -> RecommendationLevel:
        """Map an overall score to a stable recommendation band."""

        if score >= self._config.strong_match_min:
            return RecommendationLevel.STRONG_MATCH
        if score >= self._config.good_match_min:
            return RecommendationLevel.GOOD_MATCH
        if score >= self._config.possible_match_min:
            return RecommendationLevel.POSSIBLE_MATCH
        if score >= self._config.weak_match_min:
            return RecommendationLevel.WEAK_MATCH
        return RecommendationLevel.NOT_RECOMMENDED

    def _role_match(self, profile: CandidateProfile, job: JobPosting) -> float:
        title = self._normalize(job.title)
        if not profile.target_roles:
            return 50.0
        similarities = [
            self._token_similarity(title, self._normalize(role)) for role in profile.target_roles
        ]
        best = max(similarities, default=0.0)
        return min(best * 100.0 + (10.0 if best >= 0.75 else 0.0), 100.0)

    def _skill_match(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        text: str,
    ) -> tuple[list[str], list[str], float]:
        candidate_skills = self._deduplicate(
            [*profile.core_skills, *profile.supporting_skills, *profile.technologies]
        )
        job_skills = self._deduplicate(
            [
                *job.technologies,
                *self._skills_mentioned(candidate_skills, text),
                *self._known_keywords(text),
            ]
        )
        candidate_map = {self._normalize_skill(skill): skill for skill in candidate_skills}
        job_map = {self._normalize_skill(skill): skill for skill in job_skills}
        matched = [candidate_map[key] for key in candidate_map.keys() & job_map.keys()]
        missing = [job_map[key] for key in job_map.keys() - candidate_map.keys()]

        if not job_map:
            return sorted(matched), sorted(missing), 50.0
        matched_core = sum(
            1 for skill in profile.core_skills if self._normalize_skill(skill) in job_map
        )
        total_core = max(len(profile.core_skills), 1)
        coverage = len(matched) / len(job_map)
        core_coverage = matched_core / total_core
        score = min((coverage * 70.0) + (core_coverage * 30.0), 100.0)
        return sorted(matched), sorted(missing), score

    def _domain_match(self, profile: CandidateProfile, text: str) -> float:
        primary_matches = self._keyword_hits(_DOMAIN_KEYWORDS[profile.primary_domain], text)
        if primary_matches:
            return 100.0
        for domain in profile.secondary_domains:
            if self._keyword_hits(_DOMAIN_KEYWORDS[domain], text):
                return 75.0
        if profile.primary_domain == CandidateDomain.GENERAL_TECHNOLOGY:
            return 60.0
        return 20.0

    def _experience_match(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        text: str,
    ) -> float:
        early_candidate = profile.experience_level in {
            ExperienceLevel.STUDENT,
            ExperienceLevel.INTERNSHIP,
            ExperienceLevel.ENTRY_LEVEL,
            ExperienceLevel.JUNIOR,
        }
        if early_candidate and has_senior_title(job.title):
            return 0.0
        if _EARLY_CAREER_PATTERN.search(f"{job.title} {text}"):
            return 100.0 if early_candidate else 70.0
        if early_candidate and job.employment_type == EmploymentType.FULL_TIME:
            return 60.0
        return 50.0

    def _employment_match(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        preferences: JobSearchPreferences | None,
        text: str,
    ) -> float:
        desired = preferences.employment_types if preferences else []
        if desired:
            mapped = self._search_employment_type(job)
            return 100.0 if mapped in desired else 35.0
        if job.employment_type == EmploymentType.INTERNSHIP or "intern" in job.title.casefold():
            return 100.0
        if _EARLY_CAREER_PATTERN.search(text):
            return 85.0
        if job.employment_type == EmploymentType.FULL_TIME:
            return 65.0
        if job.employment_type in {EmploymentType.CONTRACT, EmploymentType.TEMPORARY}:
            return 30.0
        return 50.0

    def _location_match(
        self,
        job: JobPosting,
        preferences: JobSearchPreferences | None,
    ) -> tuple[float, bool]:
        if preferences is None:
            return 70.0, False
        locations = [self._normalize(location) for location in preferences.desired_locations]
        job_location = self._normalize(job.location or "")
        remote_preference = preferences.remote_preference

        if job.work_arrangement == WorkArrangement.REMOTE:
            if remote_preference in {RemotePreference.REMOTE_ALLOWED, RemotePreference.REMOTE_ONLY}:
                return 100.0, False
            return 75.0, False
        if job.work_arrangement == WorkArrangement.HYBRID and remote_preference in {
            RemotePreference.HYBRID_ALLOWED,
            RemotePreference.HYBRID_ONLY,
        }:
            return 95.0, False
        if not locations:
            return 70.0, False
        if not job_location:
            return 55.0, False
        if job_location in locations:
            return 100.0, False
        if any(self._same_state(job_location, location) for location in locations):
            return 75.0, False
        return 20.0, True

    def _certification_match(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        text: str,
    ) -> tuple[list[str], float]:
        candidate = {self._normalize_skill(cert): cert for cert in profile.certifications}
        requested = self._deduplicate(
            [*job.certifications, *self._skills_mentioned(profile.certifications, text)]
        )
        requested_keys = {self._normalize_skill(cert) for cert in requested}
        matched = [candidate[key] for key in candidate.keys() & requested_keys]
        if not requested_keys:
            return sorted(matched), 70.0
        return sorted(matched), (len(matched) / len(requested_keys)) * 100.0

    def _keyword_match(self, profile: CandidateProfile, text: str) -> tuple[list[str], float]:
        job_keywords = self._known_keywords(text)
        profile_text = self._normalize(
            " ".join(
                [
                    *profile.core_skills,
                    *profile.supporting_skills,
                    *profile.technologies,
                    *profile.certifications,
                    *profile.industry_keywords,
                ]
            )
        )
        matched = [keyword for keyword in job_keywords if keyword in profile_text]
        if not job_keywords:
            return [], 50.0
        return sorted(matched), (len(matched) / len(job_keywords)) * 100.0

    def _disqualifying_flags(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        text: str,
        domain_score: float,
        location_mismatch: bool,
    ) -> list[str]:
        flags: list[str] = []
        early_candidate = profile.experience_level in {
            ExperienceLevel.STUDENT,
            ExperienceLevel.INTERNSHIP,
            ExperienceLevel.ENTRY_LEVEL,
            ExperienceLevel.JUNIOR,
        }
        if early_candidate and has_senior_title(job.title):
            flags.append("senior_level_role")
        if _CLEARANCE_PATTERN.search(text):
            flags.append("requires_clearance")
        if _MASTERS_PATTERN.search(text):
            flags.append("requires_masters_degree")
        if _YEARS_PATTERN.search(text):
            flags.append("requires_5_plus_years")
        if domain_score <= 20.0:
            flags.append("unrelated_domain")
        if early_candidate and not _EARLY_CAREER_PATTERN.search(f"{job.title} {text}"):
            flags.append("non_internship_role")
        if location_mismatch:
            flags.append("location_mismatch")
        return flags

    def _warnings(
        self,
        job: JobPosting,
        missing_skills: Sequence[str],
        flags: Sequence[str],
    ) -> list[str]:
        warnings = [flag.replace("_", " ") for flag in flags]
        if not job.description:
            warnings.append("job description is empty")
        if missing_skills:
            warnings.append(f"missing skills: {', '.join(missing_skills[:5])}")
        return warnings

    def _explanation(
        self,
        profile: CandidateProfile,
        job: JobPosting,
        matched_skills: Sequence[str],
        missing_skills: Sequence[str],
        matched_certifications: Sequence[str],
        flags: Sequence[str],
    ) -> str:
        reasons: list[str] = []
        if "intern" in job.title.casefold() or job.employment_type == EmploymentType.INTERNSHIP:
            reasons.append("the role is internship-level")
        if matched_skills:
            reasons.append(f"it matches {', '.join(matched_skills[:4])}")
        if matched_certifications:
            reasons.append(f"it matches {', '.join(matched_certifications[:2])}")
        if profile.primary_domain.value.casefold() in self._job_text(job):
            reasons.append(f"it aligns with {profile.primary_domain.value}")
        if not reasons:
            reasons.append("it has limited direct evidence alignment")

        explanation = f"This job was scored because {'; '.join(reasons)}."
        if missing_skills:
            explanation += f" Missing skills include {', '.join(missing_skills[:5])}."
        if flags:
            explanation += f" Flags include {', '.join(flag.replace('_', ' ') for flag in flags)}."
        return explanation

    def _sort_key(self, item: tuple[JobPosting, JobFitScore]) -> tuple[object, ...]:
        job, score = item
        recommendation_order = {
            RecommendationLevel.STRONG_MATCH: 0,
            RecommendationLevel.GOOD_MATCH: 1,
            RecommendationLevel.POSSIBLE_MATCH: 2,
            RecommendationLevel.WEAK_MATCH: 3,
            RecommendationLevel.NOT_RECOMMENDED: 4,
        }
        recommendation = self.recommendation_level(score.overall_score)
        posted_ordinal = job.posted_date.toordinal() if isinstance(job.posted_date, date) else 0
        return (
            -score.overall_score,
            recommendation_order[recommendation],
            -score.role_match_score,
            -posted_ordinal,
            job.company.casefold(),
            job.title.casefold(),
            job.id,
        )

    def _job_text(self, job: JobPosting) -> str:
        values = [
            job.title,
            job.description or "",
            *job.responsibilities,
            *job.requirements,
            *job.preferred_qualifications,
            *job.technologies,
            *job.certifications,
        ]
        return self._normalize(plain_text_from_html(" ".join(values)))

    def _skills_mentioned(self, skills: Iterable[str], text: str) -> list[str]:
        return [skill for skill in skills if self._normalize_skill(skill) in text]

    def _known_keywords(self, text: str) -> list[str]:
        return sorted(keyword for keyword in _KEYWORDS if keyword in text)

    def _keyword_hits(self, keywords: Iterable[str], text: str) -> list[str]:
        return [keyword for keyword in keywords if keyword in text]

    def _search_employment_type(self, job: JobPosting) -> SearchEmploymentType | None:
        mappings = {
            EmploymentType.INTERNSHIP: SearchEmploymentType.INTERNSHIP,
            EmploymentType.FULL_TIME: SearchEmploymentType.FULL_TIME,
            EmploymentType.PART_TIME: SearchEmploymentType.PART_TIME,
            EmploymentType.CONTRACT: SearchEmploymentType.CONTRACT,
        }
        return mappings.get(job.employment_type)

    def _same_state(self, first: str, second: str) -> bool:
        first_tokens = first.split()
        second_tokens = second.split()
        return bool(first_tokens and second_tokens and first_tokens[-1] == second_tokens[-1])

    def _token_similarity(self, first: str, second: str) -> float:
        first_tokens = set(first.split())
        second_tokens = set(second.split())
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    def _normalize_skill(self, value: str) -> str:
        return self._normalize(normalize_skill_name(value))

    def _normalize(self, value: str) -> str:
        return JobPosting._normalize_identity_text(value)

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = self._normalize_skill(value)
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result
