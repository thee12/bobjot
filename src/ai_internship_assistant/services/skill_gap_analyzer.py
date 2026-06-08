"""Deterministic, factual comparison of CandidateProfile and JobAnalysis."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ai_internship_assistant.domain.models import (
    CandidateProfile,
    CertificationGap,
    ConcernSeverity,
    DisqualifyingConcern,
    ExperienceLevel,
    GapSeverity,
    JobAnalysis,
    JobSeniority,
    MatchType,
    RequirementLevel,
    ResumeEmphasisOpportunity,
    SkillGap,
    SkillGapReport,
    SkillMatch,
    SkillRequirement,
)
from ai_internship_assistant.utils import (
    canonical_skill_name,
    deduplicate_match_terms,
    normalize_match_term,
    related_job_terms,
)


class SkillGapAnalysisError(TypeError):
    """Raised when the analyzer receives invalid programmer input."""


@dataclass(frozen=True, slots=True)
class SkillGapAnalysisConfig:
    """Configurable thresholds for aggregate gap severity."""

    high_required_gap_count: int = 3
    critical_required_gap_count: int = 5
    high_concern_count: int = 2


class SkillGapAnalyzer:
    """Compare explicit candidate evidence with structured job requirements.

    Exact and normalized matches are evidence-backed. Related matches only
    create emphasis opportunities and never claim the candidate has the skill.
    """

    def __init__(self, config: SkillGapAnalysisConfig | None = None) -> None:
        self._config = config or SkillGapAnalysisConfig()

    def analyze(
        self,
        candidate_profile: CandidateProfile,
        job_analysis: JobAnalysis,
    ) -> SkillGapReport:
        """Return a separate skill-gap report without mutating either input."""

        if not isinstance(candidate_profile, CandidateProfile):
            msg = "candidate_profile must be a CandidateProfile instance"
            raise SkillGapAnalysisError(msg)
        if not isinstance(job_analysis, JobAnalysis):
            msg = "job_analysis must be a JobAnalysis instance"
            raise SkillGapAnalysisError(msg)

        candidate_skills = deduplicate_match_terms(
            [
                *candidate_profile.core_skills,
                *candidate_profile.supporting_skills,
                *candidate_profile.technologies,
            ]
        )
        candidate_map = {canonical_skill_name(skill): skill for skill in candidate_skills}

        matched_required, missing_required = self._compare_requirements(
            job_analysis.required_skills,
            candidate_map,
            job_analysis,
            required=True,
        )
        matched_preferred, missing_preferred = self._compare_requirements(
            job_analysis.preferred_skills,
            candidate_map,
            job_analysis,
            required=False,
        )
        matched_certifications, missing_certifications = self._compare_certifications(
            candidate_profile,
            job_analysis,
        )
        opportunities = self._emphasis_opportunities(
            candidate_skills,
            job_analysis,
            [*missing_required, *missing_preferred],
        )
        concerns = self._concerns(candidate_profile, job_analysis)
        learning = self._learning_recommendations(
            [*missing_required, *missing_preferred],
            missing_certifications,
        )
        overall = self._overall_severity(
            job_analysis,
            missing_required,
            missing_preferred,
            concerns,
        )
        warnings = self._warnings(candidate_skills, job_analysis)

        return SkillGapReport(
            job_id=job_analysis.job_id,
            candidate_name=candidate_profile.candidate_name,
            matched_required_skills=matched_required,
            matched_preferred_skills=matched_preferred,
            missing_required_skills=missing_required,
            missing_preferred_skills=missing_preferred,
            matched_certifications=matched_certifications,
            missing_certifications=missing_certifications,
            disqualifying_concerns=concerns,
            resume_emphasis_opportunities=opportunities,
            learning_recommendations=learning,
            overall_gap_severity=overall,
            match_summary=self._summary(
                matched_required,
                matched_preferred,
                missing_required,
                missing_preferred,
                opportunities,
                concerns,
            ),
            warnings=warnings,
        )

    def _compare_requirements(
        self,
        requirements: Sequence[SkillRequirement],
        candidate_map: dict[str, str],
        job_analysis: JobAnalysis,
        *,
        required: bool,
    ) -> tuple[list[SkillMatch], list[SkillGap]]:
        matches: list[SkillMatch] = []
        gaps: list[SkillGap] = []
        seen: set[str] = set()

        for requirement in requirements:
            canonical = canonical_skill_name(requirement.name)
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            candidate_evidence = candidate_map.get(canonical)
            if candidate_evidence:
                match_type = self._match_type(candidate_evidence, requirement.name)
                matches.append(
                    SkillMatch(
                        skill_name=requirement.name,
                        candidate_evidence=candidate_evidence,
                        job_evidence=requirement.evidence,
                        match_type=match_type,
                        confidence=1.0 if match_type == MatchType.EXACT else 0.95,
                    )
                )
                continue

            related = self._related_candidate_skill(candidate_map.values(), requirement.name)
            gaps.append(
                SkillGap(
                    skill_name=requirement.name,
                    requirement_level=requirement.requirement_level,
                    job_evidence=requirement.evidence,
                    gap_severity=self._skill_gap_severity(
                        job_analysis,
                        required=required,
                        has_related=related is not None,
                    ),
                    recommendation=self._skill_recommendation(requirement.name),
                    safe_to_add_to_resume=False,
                )
            )
        return matches, gaps

    def _compare_certifications(
        self,
        profile: CandidateProfile,
        job: JobAnalysis,
    ) -> tuple[list[SkillMatch], list[CertificationGap]]:
        candidate_map = {
            canonical_skill_name(certification): certification
            for certification in deduplicate_match_terms(profile.certifications)
        }
        matched: list[SkillMatch] = []
        missing: list[CertificationGap] = []

        for certification in deduplicate_match_terms(job.certifications):
            canonical = canonical_skill_name(certification)
            level, evidence = self._certification_context(certification, job)
            candidate_evidence = candidate_map.get(canonical)
            if candidate_evidence:
                match_type = self._match_type(candidate_evidence, certification)
                matched.append(
                    SkillMatch(
                        skill_name=certification,
                        candidate_evidence=candidate_evidence,
                        job_evidence=evidence,
                        match_type=match_type,
                        confidence=1.0 if match_type == MatchType.EXACT else 0.95,
                    )
                )
                continue
            missing.append(
                CertificationGap(
                    certification_name=certification,
                    requirement_level=level,
                    candidate_has_certification=False,
                    gap_severity=self._certification_gap_severity(level, job),
                    recommendation=(
                        f"Learn about {certification} and consider pursuing it later; "
                        "do not add it to the resume unless earned."
                    ),
                )
            )
        return matched, missing

    def _certification_context(
        self,
        certification: str,
        job: JobAnalysis,
    ) -> tuple[RequirementLevel, str]:
        canonical = canonical_skill_name(certification)
        requirements = [*job.required_skills, *job.preferred_skills]
        for requirement in requirements:
            if canonical_skill_name(requirement.name) == canonical:
                return requirement.requirement_level, requirement.evidence
        return RequirementLevel.UNKNOWN, certification

    def _emphasis_opportunities(
        self,
        candidate_skills: Sequence[str],
        job: JobAnalysis,
        gaps: Sequence[SkillGap],
    ) -> list[ResumeEmphasisOpportunity]:
        job_terms = deduplicate_match_terms(
            [
                *(gap.skill_name for gap in gaps),
                *job.ats_keywords,
                *job.cybersecurity_terms,
            ]
        )
        opportunities: list[ResumeEmphasisOpportunity] = []
        seen: set[tuple[str, str]] = set()

        for candidate_skill in candidate_skills:
            related = {canonical_skill_name(term) for term in related_job_terms(candidate_skill)}
            for job_term in job_terms:
                key = (canonical_skill_name(candidate_skill), canonical_skill_name(job_term))
                if key[1] not in related or key in seen:
                    continue
                seen.add(key)
                opportunities.append(
                    ResumeEmphasisOpportunity(
                        existing_candidate_skill=candidate_skill,
                        related_job_keyword=job_term,
                        explanation=(
                            f"{candidate_skill} is related to {job_term}, but is not equivalent."
                        ),
                        safe_resume_strategy=(
                            f"Emphasize existing {candidate_skill} evidence when relevant to "
                            f"{job_term}; do not claim direct {job_term} experience."
                        ),
                    )
                )
        return opportunities

    def _concerns(
        self,
        profile: CandidateProfile,
        job: JobAnalysis,
    ) -> list[DisqualifyingConcern]:
        return [
            DisqualifyingConcern(
                concern_type=self._concern_type(requirement),
                description=(
                    f"The posting states: {requirement}. Verify eligibility before applying."
                ),
                evidence=requirement,
                severity=self._concern_severity(requirement, profile),
            )
            for requirement in job.disqualifying_requirements
        ]

    def _concern_type(self, requirement: str) -> str:
        normalized = normalize_match_term(requirement)
        mappings = (
            ("clearance", "security_clearance"),
            ("citizenship", "citizenship"),
            ("years", "experience_requirement"),
            ("master", "education_requirement"),
            ("relocat", "relocation"),
            ("travel", "travel"),
            ("local", "geographic_requirement"),
            ("availability", "availability"),
        )
        return next((label for token, label in mappings if token in normalized), "other")

    def _concern_severity(
        self,
        requirement: str,
        profile: CandidateProfile,
    ) -> ConcernSeverity:
        normalized = normalize_match_term(requirement)
        early = profile.experience_level in {
            ExperienceLevel.STUDENT,
            ExperienceLevel.INTERNSHIP,
            ExperienceLevel.ENTRY_LEVEL,
            ExperienceLevel.JUNIOR,
        }
        if early and ("5+ years" in requirement.casefold() or "requires 5" in normalized):
            return ConcernSeverity.DISQUALIFYING
        if "clearance" in normalized or "citizenship" in normalized:
            return ConcernSeverity.HIGH
        if "master" in normalized or "full time availability" in normalized:
            return ConcernSeverity.HIGH
        if "relocat" in normalized or "local" in normalized or "travel" in normalized:
            return ConcernSeverity.WARNING
        return ConcernSeverity.INFO

    def _skill_gap_severity(
        self,
        job: JobAnalysis,
        *,
        required: bool,
        has_related: bool,
    ) -> GapSeverity:
        if not required:
            return GapSeverity.LOW
        if job.seniority == JobSeniority.INTERNSHIP:
            return GapSeverity.LOW if has_related else GapSeverity.MEDIUM
        return GapSeverity.MEDIUM if has_related else GapSeverity.HIGH

    def _certification_gap_severity(
        self,
        level: RequirementLevel,
        job: JobAnalysis,
    ) -> GapSeverity:
        if level in {RequirementLevel.PREFERRED, RequirementLevel.NICE_TO_HAVE}:
            return GapSeverity.LOW
        if level == RequirementLevel.REQUIRED:
            if job.seniority == JobSeniority.INTERNSHIP:
                return GapSeverity.MEDIUM
            return GapSeverity.HIGH
        return GapSeverity.LOW

    def _overall_severity(
        self,
        job: JobAnalysis,
        required: Sequence[SkillGap],
        preferred: Sequence[SkillGap],
        concerns: Sequence[DisqualifyingConcern],
    ) -> GapSeverity:
        if any(concern.severity == ConcernSeverity.DISQUALIFYING for concern in concerns):
            return GapSeverity.CRITICAL
        if len(required) >= self._config.critical_required_gap_count:
            return GapSeverity.CRITICAL
        high_concerns = sum(concern.severity == ConcernSeverity.HIGH for concern in concerns)
        if len(required) >= self._config.high_required_gap_count:
            return GapSeverity.HIGH
        if high_concerns >= self._config.high_concern_count:
            return GapSeverity.HIGH
        if required or concerns or len(preferred) >= 2:
            return GapSeverity.MEDIUM
        if preferred:
            return GapSeverity.LOW
        if job.required_skills or job.preferred_skills:
            return GapSeverity.LOW
        return GapSeverity.LOW

    def _related_candidate_skill(
        self,
        candidate_skills: Iterable[str],
        job_skill: str,
    ) -> str | None:
        job_canonical = canonical_skill_name(job_skill)
        return next(
            (
                skill
                for skill in candidate_skills
                if job_canonical
                in {canonical_skill_name(term) for term in related_job_terms(skill)}
            ),
            None,
        )

    def _match_type(self, candidate: str, job: str) -> MatchType:
        if candidate.strip().casefold() == job.strip().casefold():
            return MatchType.EXACT
        return MatchType.NORMALIZED

    def _skill_recommendation(self, skill: str) -> str:
        normalized = canonical_skill_name(skill)
        specific = {
            canonical_skill_name("Splunk"): (
                "Complete a beginner Splunk lab and add it only after completing "
                "work that demonstrates actual usage."
            ),
            canonical_skill_name("SIEM"): (
                "Complete a beginner SIEM lab and add it only after completing "
                "work that demonstrates actual usage."
            ),
            canonical_skill_name("MITRE ATT&CK"): (
                "Study MITRE ATT&CK fundamentals and apply them in a small "
                "threat-detection or incident-analysis project."
            ),
        }
        return specific.get(
            normalized,
            f"Learn {skill} through a small practical lab or project before adding it to a resume.",
        )

    def _learning_recommendations(
        self,
        gaps: Sequence[SkillGap],
        certification_gaps: Sequence[CertificationGap],
    ) -> list[str]:
        return self._deduplicate(
            [
                *(gap.recommendation for gap in gaps),
                *(gap.recommendation for gap in certification_gaps),
            ]
        )

    def _summary(
        self,
        matched_required: Sequence[SkillMatch],
        matched_preferred: Sequence[SkillMatch],
        missing_required: Sequence[SkillGap],
        missing_preferred: Sequence[SkillGap],
        opportunities: Sequence[ResumeEmphasisOpportunity],
        concerns: Sequence[DisqualifyingConcern],
    ) -> str:
        matched = [match.skill_name for match in [*matched_required, *matched_preferred]]
        missing = [gap.skill_name for gap in [*missing_required, *missing_preferred]]
        parts = [
            (
                f"The candidate matches {', '.join(matched[:5])}."
                if matched
                else "No direct candidate skill matches were identified."
            )
        ]
        if missing:
            parts.append(f"Missing skills include {', '.join(missing[:5])}.")
        if opportunities:
            first = opportunities[0]
            parts.append(
                f"{first.existing_candidate_skill} may support safe emphasis around "
                f"{first.related_job_keyword}, but it is not a direct match."
            )
        if concerns:
            parts.append(f"The posting contains {len(concerns)} concern(s) requiring review.")
        return " ".join(parts)

    def _warnings(self, candidate_skills: Sequence[str], job: JobAnalysis) -> list[str]:
        warnings: list[str] = []
        if not candidate_skills:
            warnings.append("candidate profile contains no skills or technologies")
        if not job.required_skills and not job.preferred_skills:
            warnings.append("job analysis contains no required or preferred skills")
        if job.confidence_score < 0.5:
            warnings.append("job analysis confidence is low")
        return warnings

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result
