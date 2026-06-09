"""Deterministic estimated ATS resume/job match scoring.

This service approximates resume alignment using transparent component weights.
It does not model or guarantee the behavior of any proprietary ATS.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ai_internship_assistant.domain.models import (
    ATSComponentScores,
    ATSMatchReport,
    ATSRecommendationLevel,
    CandidateDomain,
    CandidateProfile,
    ConcernSeverity,
    ExperienceLevel,
    JobAnalysis,
    JobSeniority,
    KeywordCoverage,
    OptimizationPriority,
    Resume,
    ResumeSectionScore,
    RoleCategory,
    SkillGap,
    SkillGapReport,
)
from ai_internship_assistant.utils import canonical_skill_name, deduplicate_match_terms

_SCORING_VERSION = "estimated-ats-v1"

_ROLE_DOMAIN_MAP: dict[RoleCategory, set[CandidateDomain]] = {
    RoleCategory.CYBERSECURITY: {CandidateDomain.CYBERSECURITY},
    RoleCategory.SOFTWARE_ENGINEERING: {
        CandidateDomain.SOFTWARE_ENGINEERING,
        CandidateDomain.WEB_DEVELOPMENT,
    },
    RoleCategory.NETWORKING: {CandidateDomain.NETWORKING},
    RoleCategory.IT_SUPPORT: {CandidateDomain.IT_SUPPORT},
    RoleCategory.CLOUD: {CandidateDomain.CLOUD_ENGINEERING},
    RoleCategory.DATA: {CandidateDomain.DATA_SCIENCE, CandidateDomain.MACHINE_LEARNING},
    RoleCategory.DEVOPS: {CandidateDomain.DEVOPS, CandidateDomain.SYSTEMS_ADMINISTRATION},
    RoleCategory.UNKNOWN: set(),
}


class ATSMatchScoringError(TypeError):
    """Raised when scoring receives invalid or inconsistent programmer input."""


@dataclass(frozen=True, slots=True)
class ATSMatchScoringConfig:
    """Centralized estimated ATS weights, thresholds, and penalties."""

    required_skill_weight: float = 0.30
    keyword_weight: float = 0.25
    role_alignment_weight: float = 0.15
    preferred_skill_weight: float = 0.10
    certification_weight: float = 0.075
    experience_level_weight: float = 0.075
    education_weight: float = 0.05
    neutral_score: float = 70.0
    concern_penalties: dict[ConcernSeverity, float] = field(
        default_factory=lambda: {
            ConcernSeverity.INFO: 5.0,
            ConcernSeverity.WARNING: 10.0,
            ConcernSeverity.HIGH: 20.0,
            ConcernSeverity.DISQUALIFYING: 40.0,
        }
    )
    excellent_match_min: float = 90.0
    strong_match_min: float = 80.0
    good_match_min: float = 70.0
    possible_match_min: float = 60.0
    weak_match_min: float = 40.0

    def __post_init__(self) -> None:
        total = (
            self.required_skill_weight
            + self.keyword_weight
            + self.role_alignment_weight
            + self.preferred_skill_weight
            + self.certification_weight
            + self.experience_level_weight
            + self.education_weight
        )
        if abs(total - 1.0) > 0.0001:
            msg = f"ATS scoring weights must total 1.0, got {total}"
            raise ValueError(msg)


class ATSMatchScoringService:
    """Score current factual resume alignment against a structured job."""

    def __init__(self, config: ATSMatchScoringConfig | None = None) -> None:
        self._config = config or ATSMatchScoringConfig()

    def score(
        self,
        resume: Resume,
        candidate_profile: CandidateProfile,
        job_analysis: JobAnalysis,
        skill_gap_report: SkillGapReport,
    ) -> ATSMatchReport:
        """Return an explainable estimated ATS match report without mutation."""

        self._validate_inputs(resume, candidate_profile, job_analysis, skill_gap_report)
        sections = self._resume_sections(resume)
        evidence_terms = self._candidate_evidence_terms(resume, candidate_profile)
        matched_keywords, missing_keywords = self._keyword_matches(
            job_analysis.ats_keywords,
            evidence_terms,
        )
        high_value = self._high_value_keywords(job_analysis)
        high_value_matched, high_value_missing = self._keyword_matches(
            high_value,
            evidence_terms,
        )
        keyword_score = self._coverage(len(matched_keywords), len(job_analysis.ats_keywords))
        required_score = self._coverage(
            len(skill_gap_report.matched_required_skills),
            len(skill_gap_report.matched_required_skills)
            + len(skill_gap_report.missing_required_skills),
        )
        preferred_score = self._coverage(
            len(skill_gap_report.matched_preferred_skills),
            len(skill_gap_report.matched_preferred_skills)
            + len(skill_gap_report.missing_preferred_skills),
        )
        certification_score = self._coverage(
            len(skill_gap_report.matched_certifications),
            len(skill_gap_report.matched_certifications)
            + len(skill_gap_report.missing_certifications),
        )
        role_score = self._role_alignment(candidate_profile, job_analysis)
        experience_score = self._experience_alignment(candidate_profile, job_analysis)
        education_score = self._education_alignment(resume, candidate_profile, job_analysis)
        section_scores = self._section_scores(
            sections,
            job_analysis.ats_keywords,
            skill_gap_report.missing_required_skills,
        )
        resume_quality_score = self._resume_quality(section_scores)
        penalty = min(
            sum(
                self._config.concern_penalties[concern.severity]
                for concern in skill_gap_report.disqualifying_concerns
            ),
            100.0,
        )
        weighted = (
            required_score * self._config.required_skill_weight
            + keyword_score * self._config.keyword_weight
            + role_score * self._config.role_alignment_weight
            + preferred_score * self._config.preferred_skill_weight
            + certification_score * self._config.certification_weight
            + experience_score * self._config.experience_level_weight
            + education_score * self._config.education_weight
        )
        overall = round(min(max(weighted - penalty, 0.0), 100.0), 1)
        recommendation = self.recommendation_level(overall)
        priority = self._optimization_priority(
            overall,
            skill_gap_report,
            missing_keywords,
        )

        return ATSMatchReport(
            job_id=job_analysis.job_id,
            candidate_name=candidate_profile.candidate_name or resume.full_name,
            overall_score=overall,
            recommendation_level=recommendation,
            component_scores=ATSComponentScores(
                keyword_score=keyword_score,
                required_skill_score=required_score,
                preferred_skill_score=preferred_score,
                certification_score=certification_score,
                role_alignment_score=role_score,
                experience_level_score=experience_score,
                education_score=education_score,
                resume_quality_score=resume_quality_score,
                disqualifier_penalty=penalty,
            ),
            keyword_coverage=KeywordCoverage(
                total_keywords=len(deduplicate_match_terms(job_analysis.ats_keywords)),
                matched_keywords=len(matched_keywords),
                missing_keywords=len(missing_keywords),
                coverage_percentage=keyword_score,
                high_value_matched_keywords=high_value_matched,
                high_value_missing_keywords=high_value_missing,
            ),
            required_skill_coverage=required_score,
            preferred_skill_coverage=preferred_score,
            certification_coverage=certification_score,
            role_alignment_score=role_score,
            experience_alignment_score=experience_score,
            education_alignment_score=education_score,
            resume_section_scores=section_scores,
            matched_ats_keywords=matched_keywords,
            missing_ats_keywords=missing_keywords,
            matched_required_skills=[
                match.skill_name for match in skill_gap_report.matched_required_skills
            ],
            missing_required_skills=[
                gap.skill_name for gap in skill_gap_report.missing_required_skills
            ],
            matched_preferred_skills=[
                match.skill_name for match in skill_gap_report.matched_preferred_skills
            ],
            missing_preferred_skills=[
                gap.skill_name for gap in skill_gap_report.missing_preferred_skills
            ],
            matched_certifications=[
                match.skill_name for match in skill_gap_report.matched_certifications
            ],
            missing_certifications=[
                gap.certification_name for gap in skill_gap_report.missing_certifications
            ],
            disqualifying_concerns=skill_gap_report.disqualifying_concerns,
            optimization_priority=priority,
            optimization_guidance=self._optimization_guidance(
                skill_gap_report,
                matched_keywords,
                missing_keywords,
                section_scores,
            ),
            warnings=self._warnings(
                resume,
                candidate_profile,
                job_analysis,
                skill_gap_report,
            ),
            scoring_version=_SCORING_VERSION,
        )

    def recommendation_level(self, score: float) -> ATSRecommendationLevel:
        """Map a numeric estimated score to a stable interpretation band."""

        if score >= self._config.excellent_match_min:
            return ATSRecommendationLevel.EXCELLENT_MATCH
        if score >= self._config.strong_match_min:
            return ATSRecommendationLevel.STRONG_MATCH
        if score >= self._config.good_match_min:
            return ATSRecommendationLevel.GOOD_MATCH
        if score >= self._config.possible_match_min:
            return ATSRecommendationLevel.POSSIBLE_MATCH
        if score >= self._config.weak_match_min:
            return ATSRecommendationLevel.WEAK_MATCH
        return ATSRecommendationLevel.NOT_RECOMMENDED

    def _validate_inputs(
        self,
        resume: Resume,
        profile: CandidateProfile,
        job: JobAnalysis,
        gap: SkillGapReport,
    ) -> None:
        if not isinstance(resume, Resume):
            raise ATSMatchScoringError("resume must be a Resume instance")
        if not isinstance(profile, CandidateProfile):
            raise ATSMatchScoringError("candidate_profile must be a CandidateProfile instance")
        if not isinstance(job, JobAnalysis):
            raise ATSMatchScoringError("job_analysis must be a JobAnalysis instance")
        if not isinstance(gap, SkillGapReport):
            raise ATSMatchScoringError("skill_gap_report must be a SkillGapReport instance")
        if job.job_id != gap.job_id:
            raise ATSMatchScoringError("job_analysis and skill_gap_report job IDs must match")

    def _coverage(self, matched: int, total: int) -> float:
        if total == 0:
            return self._config.neutral_score
        return round((matched / total) * 100.0, 1)

    def _candidate_evidence_terms(
        self,
        resume: Resume,
        profile: CandidateProfile,
    ) -> list[str]:
        values = [
            *profile.core_skills,
            *profile.supporting_skills,
            *profile.technologies,
            *profile.certifications,
            *profile.target_roles,
            *profile.industry_keywords,
            *self._all_resume_strings(resume),
        ]
        return deduplicate_match_terms(values)

    def _keyword_matches(
        self,
        keywords: Iterable[str],
        evidence_terms: Sequence[str],
    ) -> tuple[list[str], list[str]]:
        evidence_canonical = {canonical_skill_name(term) for term in evidence_terms}
        evidence_text = " ".join(evidence_terms).casefold()
        matched: list[str] = []
        missing: list[str] = []
        for keyword in deduplicate_match_terms(keywords):
            canonical = canonical_skill_name(keyword)
            if canonical in evidence_canonical or keyword.casefold() in evidence_text:
                matched.append(keyword)
            else:
                missing.append(keyword)
        return matched, missing

    def _high_value_keywords(self, job: JobAnalysis) -> list[str]:
        return deduplicate_match_terms(
            [
                job.job_title,
                *(requirement.name for requirement in job.required_skills),
                *job.certifications,
                *job.technical_tools,
                *job.programming_languages,
                *job.frameworks,
                *job.cloud_platforms,
                *job.cybersecurity_terms,
            ]
        )

    def _role_alignment(self, profile: CandidateProfile, job: JobAnalysis) -> float:
        title = canonical_skill_name(job.job_title)
        role_scores = [
            self._token_similarity(canonical_skill_name(role), title) * 100.0
            for role in profile.target_roles
        ]
        best_role = max(role_scores, default=0.0)
        aligned_domains = (
            _ROLE_DOMAIN_MAP[job.role_category] | _ROLE_DOMAIN_MAP[job.domain_category]
        )
        if profile.primary_domain in aligned_domains:
            domain_score = 100.0
        elif any(domain in aligned_domains for domain in profile.secondary_domains):
            domain_score = 75.0
        elif job.role_category == RoleCategory.UNKNOWN:
            domain_score = self._config.neutral_score
        else:
            domain_score = 20.0
        if not profile.target_roles:
            best_role = self._config.neutral_score
        return round((best_role * 0.65) + (domain_score * 0.35), 1)

    def _experience_alignment(self, profile: CandidateProfile, job: JobAnalysis) -> float:
        early = profile.experience_level in {
            ExperienceLevel.STUDENT,
            ExperienceLevel.INTERNSHIP,
            ExperienceLevel.ENTRY_LEVEL,
            ExperienceLevel.JUNIOR,
        }
        if early and job.seniority == JobSeniority.INTERNSHIP:
            return 100.0
        if early and job.seniority in {JobSeniority.ENTRY_LEVEL, JobSeniority.JUNIOR}:
            return 90.0
        if early and job.seniority == JobSeniority.MID_LEVEL:
            return 45.0
        if early and job.seniority == JobSeniority.SENIOR:
            return 10.0
        if job.seniority == JobSeniority.UNKNOWN:
            return self._config.neutral_score
        return 80.0

    def _education_alignment(
        self,
        resume: Resume,
        profile: CandidateProfile,
        job: JobAnalysis,
    ) -> float:
        if not job.education_requirements:
            return self._config.neutral_score
        candidate_text = canonical_skill_name(
            " ".join(
                [
                    profile.education_level or "",
                    *(
                        part
                        for education in resume.education
                        for part in (
                            education.institution,
                            education.degree or "",
                            education.program or "",
                            *education.details,
                        )
                    ),
                ]
            )
        )
        if not candidate_text:
            return 0.0
        requirements = canonical_skill_name(" ".join(job.education_requirements))
        if "master" in requirements and "master" not in candidate_text:
            return 20.0
        fields = (
            "computer science",
            "cybersecurity",
            "information technology",
            "data science",
            "software engineering",
        )
        if any(field in requirements and field in candidate_text for field in fields):
            return 100.0
        degree_pairs = (("bachelor", "bachelor"), ("associate", "associate"), ("master", "master"))
        if any(
            job_level in requirements and candidate_level in candidate_text
            for job_level, candidate_level in degree_pairs
        ):
            return 90.0
        if "related field" in requirements and resume.education:
            return 80.0
        return 45.0

    def _resume_sections(self, resume: Resume) -> dict[str, list[str]]:
        return {
            "Skills": [skill.name for skill in resume.skills],
            "Projects": [
                part
                for project in resume.projects
                for part in (
                    project.name,
                    project.description or "",
                    *project.bullets,
                    *project.technologies,
                )
                if part
            ],
            "Experience": [
                part
                for experience in resume.experience
                for part in (
                    experience.title,
                    experience.organization,
                    *experience.bullets,
                    *experience.technologies,
                )
                if part
            ],
            "Certifications": [certification.name for certification in resume.certifications],
            "Education": [
                part
                for education in resume.education
                for part in (
                    education.institution,
                    education.degree or "",
                    education.program or "",
                    *education.details,
                )
                if part
            ],
        }

    def _section_scores(
        self,
        sections: dict[str, list[str]],
        keywords: Sequence[str],
        missing_required: Sequence[SkillGap],
    ) -> list[ResumeSectionScore]:
        scores: list[ResumeSectionScore] = []
        unsafe = [gap.skill_name for gap in missing_required if not gap.safe_to_add_to_resume]
        for name, values in sections.items():
            matched, missing = self._keyword_matches(keywords, values)
            coverage = self._coverage(len(matched), len(deduplicate_match_terms(keywords)))
            completeness = 100.0 if values else 0.0
            score = round((coverage * 0.8) + (completeness * 0.2), 1)
            strengths = [f"Contains ATS keyword: {keyword}" for keyword in matched[:5]]
            weaknesses = [] if values else [f"{name} section is missing or empty"]
            if values and not matched and keywords:
                weaknesses.append("Contains no detected ATS keywords")
            opportunities = [
                f"Do not add {keyword} unless supported by actual experience."
                for keyword in unsafe[:3]
            ]
            scores.append(
                ResumeSectionScore(
                    section_name=name,
                    score=score,
                    strengths=strengths,
                    weaknesses=weaknesses,
                    missing_keywords=missing[:10],
                    improvement_opportunities=opportunities,
                )
            )
        return scores

    def _resume_quality(self, sections: Sequence[ResumeSectionScore]) -> float:
        if not sections:
            return 0.0
        return round(sum(section.score for section in sections) / len(sections), 1)

    def _optimization_priority(
        self,
        score: float,
        gap: SkillGapReport,
        missing_keywords: Sequence[str],
    ) -> OptimizationPriority:
        major = any(
            concern.severity in {ConcernSeverity.HIGH, ConcernSeverity.DISQUALIFYING}
            for concern in gap.disqualifying_concerns
        )
        if score < 40 or major:
            return OptimizationPriority.NOT_WORTH_OPTIMIZING
        if 60 <= score <= 85 and missing_keywords:
            return OptimizationPriority.HIGH
        if 45 <= score < 60 or (score > 85 and missing_keywords):
            return OptimizationPriority.MEDIUM
        return OptimizationPriority.LOW

    def _optimization_guidance(
        self,
        gap: SkillGapReport,
        matched_keywords: Sequence[str],
        missing_keywords: Sequence[str],
        sections: Sequence[ResumeSectionScore],
    ) -> list[str]:
        guidance: list[str] = []
        if matched_keywords:
            guidance.append(
                f"Emphasize existing evidence for {', '.join(matched_keywords[:5])}."
            )
        unsafe = [
            skill
            for skill in missing_keywords
            if self._is_unsafe_missing(skill, gap)
        ]
        if unsafe:
            guidance.append(
                f"Do not add {', '.join(unsafe[:5])} unless supported by actual experience."
            )
        guidance.extend(
            opportunity.safe_resume_strategy
            for opportunity in gap.resume_emphasis_opportunities[:3]
        )
        weakest = sorted(sections, key=lambda section: section.score)[:2]
        if weakest:
            guidance.append(
                f"Review the {' and '.join(section.section_name for section in weakest)} sections "
                "for factual keyword emphasis opportunities."
            )
        return self._deduplicate(guidance)

    def _is_unsafe_missing(self, keyword: str, gap: SkillGapReport) -> bool:
        canonical = canonical_skill_name(keyword)
        missing = [*gap.missing_required_skills, *gap.missing_preferred_skills]
        return any(
            canonical_skill_name(item.skill_name) == canonical and not item.safe_to_add_to_resume
            for item in missing
        )

    def _warnings(
        self,
        resume: Resume,
        profile: CandidateProfile,
        job: JobAnalysis,
        gap: SkillGapReport,
    ) -> list[str]:
        warnings = list(gap.warnings)
        if not resume.skills or not resume.education:
            warnings.append("resume is incomplete; ATS estimate may be less reliable")
        if not profile.core_skills and not profile.technologies:
            warnings.append("candidate profile contains no skills or technologies")
        if job.confidence_score < 0.5:
            warnings.append("job analysis confidence is low")
        if not job.ats_keywords:
            warnings.append("no ATS keywords were detected")
        if not job.required_skills:
            warnings.append("no required skills were detected; neutral coverage was used")
        if len(gap.missing_required_skills) >= 3:
            warnings.append("many required skills are missing")
        if any(
            concern.severity in {ConcernSeverity.HIGH, ConcernSeverity.DISQUALIFYING}
            for concern in gap.disqualifying_concerns
        ):
            warnings.append("major job-fit concerns may limit the usefulness of optimization")
        return self._deduplicate(warnings)

    def _all_resume_strings(self, resume: Resume) -> list[str]:
        values = [resume.summary or "", *(skill.name for skill in resume.skills)]
        for section_values in self._resume_sections(resume).values():
            values.extend(section_values)
        return [value for value in values if value]

    def _token_similarity(self, first: str, second: str) -> float:
        first_tokens = set(first.split())
        second_tokens = set(second.split())
        if not first_tokens or not second_tokens:
            return 0.0
        return len(first_tokens & second_tokens) / len(first_tokens | second_tokens)

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result
