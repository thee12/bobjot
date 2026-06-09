"""Deterministic pre-rewrite resume optimization planning.

The planner creates an evidence-backed permission contract. It never rewrites
resume content and never authorizes claims unsupported by the source resume.
"""

from collections.abc import Iterable, Sequence

from ai_internship_assistant.domain.models import (
    ATSMatchReport,
    CandidateProfile,
    ConcernSeverity,
    ExpectedScoreImprovement,
    ExperienceEmphasisPlan,
    JobAnalysis,
    KeywordInclusionPlan,
    KeywordInclusionStatus,
    OptimizationPriority,
    OptimizationRisk,
    PlanPriority,
    ProjectEmphasisPlan,
    Resume,
    ResumeOptimizationPlan,
    RiskLevel,
    SectionOptimizationPlan,
    SkillGapReport,
    SkillReorderingPlan,
)
from ai_internship_assistant.utils import canonical_skill_name, deduplicate_match_terms

_PLANNER_VERSION = "deterministic-optimization-plan-v1"


class ResumeOptimizationPlanningError(TypeError):
    """Raised when the planner receives invalid or inconsistent inputs."""


class ResumeOptimizationPlanner:
    """Create a safe, structured plan before any resume rewriting occurs."""

    def create_plan(
        self,
        resume: Resume,
        candidate_profile: CandidateProfile,
        job_analysis: JobAnalysis,
        skill_gap_report: SkillGapReport,
        ats_match_report: ATSMatchReport,
    ) -> ResumeOptimizationPlan:
        """Create an evidence-backed plan without mutating input objects."""

        self._validate_inputs(
            resume,
            candidate_profile,
            job_analysis,
            skill_gap_report,
            ats_match_report,
        )
        resume_evidence = self._resume_evidence(resume, candidate_profile)
        keyword_plans = self._keyword_plans(
            resume_evidence,
            job_analysis,
            skill_gap_report,
            ats_match_report,
        )
        safe_keywords = [
            plan.keyword
            for plan in keyword_plans
            if plan.inclusion_status
            in {
                KeywordInclusionStatus.SAFE_TO_INCLUDE,
                KeywordInclusionStatus.SAFE_TO_EMPHASIZE,
            }
        ]
        unsafe_keywords = [
            plan.keyword
            for plan in keyword_plans
            if plan.inclusion_status
            in {
                KeywordInclusionStatus.RELATED_ONLY,
                KeywordInclusionStatus.NOT_SAFE_TO_INCLUDE,
                KeywordInclusionStatus.LEARNING_RECOMMENDATION_ONLY,
            }
        ]
        forbidden_claims = self._forbidden_claims(unsafe_keywords)
        skill_plan = self._skill_reordering_plan(resume, skill_gap_report, safe_keywords)
        project_plans = self._project_plans(
            resume,
            job_analysis,
            safe_keywords,
            forbidden_claims,
        )
        experience_plans = self._experience_plans(
            resume,
            job_analysis,
            safe_keywords,
            forbidden_claims,
        )
        priority = self._plan_priority(ats_match_report, safe_keywords, skill_gap_report)
        section_plans = self._section_plans(
            resume,
            ats_match_report,
            safe_keywords,
            unsafe_keywords,
            project_plans,
            experience_plans,
            priority,
        )
        improvement = self._expected_improvement(
            ats_match_report,
            safe_keywords,
            unsafe_keywords,
            priority,
        )
        risks = self._risks(skill_gap_report, unsafe_keywords)
        warnings = self._warnings(resume, safe_keywords, priority, skill_gap_report)

        return ResumeOptimizationPlan(
            job_id=job_analysis.job_id,
            candidate_name=candidate_profile.candidate_name or resume.full_name,
            target_job_title=job_analysis.job_title,
            target_company=job_analysis.company,
            baseline_ats_score=ats_match_report.overall_score,
            optimization_priority=priority,
            plan_summary=self._summary(
                job_analysis,
                safe_keywords,
                unsafe_keywords,
                project_plans,
                priority,
            ),
            section_plans=section_plans,
            skill_reordering_plan=skill_plan,
            project_emphasis_plan=project_plans,
            experience_emphasis_plan=experience_plans,
            keyword_inclusion_plan=keyword_plans,
            forbidden_claims=forbidden_claims,
            safe_keywords=safe_keywords,
            unsafe_keywords=unsafe_keywords,
            missing_skill_learning_recommendations=skill_gap_report.learning_recommendations,
            expected_score_improvement=improvement,
            risks=risks,
            warnings=warnings,
            planner_version=_PLANNER_VERSION,
        )

    def _validate_inputs(
        self,
        resume: Resume,
        profile: CandidateProfile,
        job: JobAnalysis,
        gap: SkillGapReport,
        ats: ATSMatchReport,
    ) -> None:
        expected = (
            (resume, Resume, "resume"),
            (profile, CandidateProfile, "candidate_profile"),
            (job, JobAnalysis, "job_analysis"),
            (gap, SkillGapReport, "skill_gap_report"),
            (ats, ATSMatchReport, "ats_match_report"),
        )
        for value, model_type, name in expected:
            if not isinstance(value, model_type):
                raise ResumeOptimizationPlanningError(f"{name} must be a {model_type.__name__}")
        if len({job.job_id, gap.job_id, ats.job_id}) != 1:
            raise ResumeOptimizationPlanningError("job IDs must match across planning inputs")

    def _keyword_plans(
        self,
        evidence: dict[str, list[str]],
        job: JobAnalysis,
        gap: SkillGapReport,
        ats: ATSMatchReport,
    ) -> list[KeywordInclusionPlan]:
        keywords = deduplicate_match_terms(
            [
                *job.ats_keywords,
                *(requirement.name for requirement in job.required_skills),
                *(requirement.name for requirement in job.preferred_skills),
                *job.certifications,
                *ats.missing_ats_keywords,
            ]
        )
        related_map = {
            canonical_skill_name(item.related_job_keyword): item
            for item in gap.resume_emphasis_opportunities
        }
        unsafe = {
            canonical_skill_name(item.skill_name): item
            for item in [*gap.missing_required_skills, *gap.missing_preferred_skills]
            if not item.safe_to_add_to_resume
        }
        matched = {
            canonical_skill_name(value)
            for value in [
                *ats.matched_ats_keywords,
                *ats.matched_required_skills,
                *ats.matched_preferred_skills,
                *ats.matched_certifications,
            ]
        }
        plans: list[KeywordInclusionPlan] = []
        for keyword in keywords:
            canonical = canonical_skill_name(keyword)
            sources = [
                section
                for section, values in evidence.items()
                if self._term_in_values(keyword, values)
            ]
            if canonical in matched and sources:
                status = KeywordInclusionStatus.SAFE_TO_INCLUDE
                risk = RiskLevel.LOW
                guidance = f"Use {keyword} only where the existing evidence supports it."
            elif canonical in related_map:
                opportunity = related_map[canonical]
                if sources:
                    status = KeywordInclusionStatus.SAFE_TO_EMPHASIZE
                else:
                    status = KeywordInclusionStatus.RELATED_ONLY
                    sources = [opportunity.existing_candidate_skill]
                risk = RiskLevel.MEDIUM
                guidance = opportunity.safe_resume_strategy
            elif sources:
                status = KeywordInclusionStatus.SAFE_TO_EMPHASIZE
                risk = RiskLevel.MEDIUM
                guidance = (
                    f"Emphasize {keyword} only where the identified resume evidence supports it."
                )
            elif canonical in unsafe:
                status = KeywordInclusionStatus.LEARNING_RECOMMENDATION_ONLY
                risk = RiskLevel.HIGH
                guidance = f"Do not add {keyword}; keep it as a learning recommendation."
            else:
                status = KeywordInclusionStatus.NOT_SAFE_TO_INCLUDE
                risk = RiskLevel.HIGH
                guidance = f"Do not include {keyword} because no candidate evidence was found."
            plans.append(
                KeywordInclusionPlan(
                    keyword=keyword,
                    inclusion_status=status,
                    evidence_source=sources,
                    target_sections=self._target_sections(sources),
                    safe_usage_guidance=guidance,
                    risk_level=risk,
                )
            )
        return plans

    def _skill_reordering_plan(
        self,
        resume: Resume,
        gap: SkillGapReport,
        safe_keywords: Sequence[str],
    ) -> SkillReorderingPlan:
        original = [skill.name for skill in resume.skills]
        required = {canonical_skill_name(match.skill_name) for match in gap.matched_required_skills}
        preferred = {
            canonical_skill_name(match.skill_name) for match in gap.matched_preferred_skills
        }
        safe = {canonical_skill_name(keyword) for keyword in safe_keywords}

        def rank(skill: str) -> tuple[int, int]:
            canonical = canonical_skill_name(skill)
            if canonical in required:
                return (0, original.index(skill))
            if canonical in preferred:
                return (1, original.index(skill))
            if canonical in safe:
                return (2, original.index(skill))
            return (3, original.index(skill))

        recommended = sorted(original, key=rank)
        promoted = [
            skill for index, skill in enumerate(recommended) if original.index(skill) > index
        ]
        demoted = [
            skill for index, skill in enumerate(recommended) if original.index(skill) < index
        ]
        return SkillReorderingPlan(
            original_skills=original,
            recommended_order=recommended,
            promoted_skills=promoted,
            demoted_skills=demoted,
            rationale=(
                "Prioritize matched required skills, then matched preferred skills, "
                "then other evidence-backed job keywords. Do not add missing skills."
            ),
        )

    def _project_plans(
        self,
        resume: Resume,
        job: JobAnalysis,
        safe_keywords: Sequence[str],
        forbidden_claims: Sequence[str],
    ) -> list[ProjectEmphasisPlan]:
        plans: list[ProjectEmphasisPlan] = []
        for project in resume.projects:
            evidence = [
                project.name,
                *(
                    value
                    for value in [
                        project.description,
                        *project.bullets,
                        *project.technologies,
                    ]
                    if value
                ),
            ]
            related = self._matching_keywords(evidence, [*safe_keywords, *job.ats_keywords])
            score = self._relevance_score(related, len(evidence))
            plans.append(
                ProjectEmphasisPlan(
                    project_name=project.name,
                    relevance_score=score,
                    related_job_keywords=related,
                    candidate_evidence=evidence,
                    recommended_strategy=(
                        "Feature this project earlier and plan factual bullet rephrasing."
                        if related
                        else "Keep this project, but place more job-relevant projects first."
                    ),
                    safe_phrasing_guidelines=[
                        "Preserve the project's actual technologies, scope, and outcomes.",
                        "Use job-aligned terminology only when supported by project evidence.",
                    ],
                    forbidden_claims=list(forbidden_claims),
                )
            )
        return sorted(plans, key=lambda plan: (-plan.relevance_score, plan.project_name))

    def _experience_plans(
        self,
        resume: Resume,
        job: JobAnalysis,
        safe_keywords: Sequence[str],
        forbidden_claims: Sequence[str],
    ) -> list[ExperienceEmphasisPlan]:
        plans: list[ExperienceEmphasisPlan] = []
        soft = set(job.soft_skills)
        for experience in resume.experience:
            evidence = [
                experience.title,
                experience.organization,
                *experience.bullets,
                *experience.technologies,
            ]
            related = self._matching_keywords(evidence, [*safe_keywords, *job.ats_keywords])
            soft_matches = self._soft_skill_matches(evidence, soft)
            related = deduplicate_match_terms([*related, *soft_matches])
            plans.append(
                ExperienceEmphasisPlan(
                    experience_name=f"{experience.title} at {experience.organization}",
                    relevance_score=self._relevance_score(related, len(evidence)),
                    related_job_keywords=related,
                    candidate_evidence=evidence,
                    recommended_strategy=(
                        "Plan factual emphasis of directly relevant technical or "
                        "soft-skill evidence."
                        if related
                        else (
                            "Keep claims unchanged and do not recast this role as "
                            "target-domain work."
                        )
                    ),
                    safe_phrasing_guidelines=[
                        "Preserve the employer, title, dates, responsibilities, and actual scope.",
                        "Nontechnical experience may support communication or teamwork "
                        "only if present.",
                    ],
                    forbidden_claims=list(forbidden_claims),
                )
            )
        return sorted(plans, key=lambda plan: (-plan.relevance_score, plan.experience_name))

    def _section_plans(
        self,
        resume: Resume,
        ats: ATSMatchReport,
        safe: Sequence[str],
        unsafe: Sequence[str],
        projects: Sequence[ProjectEmphasisPlan],
        experiences: Sequence[ExperienceEmphasisPlan],
        priority: PlanPriority,
    ) -> list[SectionOptimizationPlan]:
        section_scores = {item.section_name: item for item in ats.resume_section_scores}
        sections = (
            ("Header / Contact", bool(resume.full_name or resume.email), "Keep unchanged"),
            ("Education", bool(resume.education), "Emphasize relevant degree/program evidence"),
            ("Certifications", bool(resume.certifications), "Move relevant certifications higher"),
            ("Skills", bool(resume.skills), "Reorder existing skills by job relevance"),
            ("Projects", bool(resume.projects), "Feature the most relevant projects first"),
            ("Experience", bool(resume.experience), "Plan factual bullet emphasis later"),
        )
        plans: list[SectionOptimizationPlan] = []
        for name, present, action in sections:
            base_name = name.split(" /")[0]
            score = section_scores.get(base_name)
            target = safe[:5]
            if name == "Projects" and projects:
                target = projects[0].related_job_keywords
            if name == "Experience" and experiences:
                target = experiences[0].related_job_keywords
            section_priority = (
                priority
                if present and name in {"Skills", "Projects", "Experience"}
                else PlanPriority.LOW
            )
            plans.append(
                SectionOptimizationPlan(
                    section_name=name,
                    current_status="present" if present else "missing",
                    recommended_action=action if present else "Skip; do not invent this section",
                    priority=section_priority,
                    evidence=score.strengths if score else [],
                    target_keywords=list(target),
                    forbidden_keywords=list(unsafe),
                    notes=score.weaknesses if score else [],
                )
            )
        return plans

    def _expected_improvement(
        self,
        ats: ATSMatchReport,
        safe: Sequence[str],
        unsafe: Sequence[str],
        priority: PlanPriority,
    ) -> ExpectedScoreImprovement:
        if priority == PlanPriority.SKIP:
            low, high = 0.0, 2.0
        elif ats.overall_score >= 90:
            low, high = 1.0, 4.0
        else:
            opportunity = min(len(safe), 8)
            blocked = min(len(unsafe), 8)
            low = max(1.0, min(5.0, opportunity * 0.7))
            high = max(low + 2.0, min(12.0, opportunity * 1.5 - blocked * 0.4 + 4.0))
        return ExpectedScoreImprovement(
            low=round(low, 1),
            high=round(high, 1),
            rationale=(
                "Estimate reflects evidence-backed emphasis opportunities and is limited by "
                "unsupported missing keywords. It is not a promised ATS outcome."
            ),
        )

    def _plan_priority(
        self,
        ats: ATSMatchReport,
        safe: Sequence[str],
        gap: SkillGapReport,
    ) -> PlanPriority:
        major = any(
            concern.severity in {ConcernSeverity.HIGH, ConcernSeverity.DISQUALIFYING}
            for concern in gap.disqualifying_concerns
        )
        if major or ats.optimization_priority == OptimizationPriority.NOT_WORTH_OPTIMIZING:
            return PlanPriority.SKIP
        if ats.optimization_priority == OptimizationPriority.HIGH and safe:
            return PlanPriority.HIGH
        if ats.optimization_priority == OptimizationPriority.MEDIUM or safe:
            return PlanPriority.MEDIUM
        return PlanPriority.LOW

    def _forbidden_claims(self, unsafe_keywords: Sequence[str]) -> list[str]:
        claims: list[str] = []
        for keyword in unsafe_keywords:
            claims.extend(
                (
                    f"Used {keyword}",
                    f"Performed {keyword} work",
                    f"Built production solutions with {keyword}",
                )
            )
        return self._deduplicate(claims)

    def _risks(
        self,
        gap: SkillGapReport,
        unsafe_keywords: Sequence[str],
    ) -> list[OptimizationRisk]:
        risks = [
            OptimizationRisk(
                description=f"{keyword} appears in the job but lacks direct candidate evidence.",
                mitigation=f"Do not include {keyword}; keep it as a learning recommendation.",
                risk_level=RiskLevel.HIGH,
            )
            for keyword in unsafe_keywords
        ]
        risks.extend(
            OptimizationRisk(
                description=concern.description,
                mitigation="Verify eligibility before investing in resume optimization.",
                risk_level=RiskLevel.HIGH,
            )
            for concern in gap.disqualifying_concerns
        )
        return risks

    def _summary(
        self,
        job: JobAnalysis,
        safe: Sequence[str],
        unsafe: Sequence[str],
        projects: Sequence[ProjectEmphasisPlan],
        priority: PlanPriority,
    ) -> str:
        summary = (
            f"Optimization priority is {priority.value} for the {job.job_title} role. "
            f"Safely emphasize {', '.join(safe[:5]) or 'existing factual evidence'}."
        )
        if projects and projects[0].related_job_keywords:
            summary += f" Feature {projects[0].project_name} prominently."
        if unsafe:
            summary += f" Do not claim {', '.join(unsafe[:5])} without evidence."
        return summary

    def _warnings(
        self,
        resume: Resume,
        safe: Sequence[str],
        priority: PlanPriority,
        gap: SkillGapReport,
    ) -> list[str]:
        warnings = list(gap.warnings)
        if not safe:
            warnings.append("no safe job keywords were identified")
        if not resume.projects:
            warnings.append("resume contains no projects to emphasize")
        if not resume.experience:
            warnings.append("resume contains no experience entries to emphasize")
        if not resume.skills:
            warnings.append("resume contains no skills section to reorder")
        if priority == PlanPriority.SKIP:
            warnings.append("optimization should be skipped or reviewed due to major concerns")
        return self._deduplicate(warnings)

    def _resume_evidence(
        self,
        resume: Resume,
        profile: CandidateProfile,
    ) -> dict[str, list[str]]:
        return {
            "Skills": [skill.name for skill in resume.skills],
            "Profile": [
                *profile.core_skills,
                *profile.supporting_skills,
                *profile.technologies,
                *profile.certifications,
            ],
            "Projects": [
                value
                for project in resume.projects
                for value in (
                    project.name,
                    project.description or "",
                    *project.bullets,
                    *project.technologies,
                )
                if value
            ],
            "Experience": [
                value
                for experience in resume.experience
                for value in (
                    experience.title,
                    experience.organization,
                    *experience.bullets,
                    *experience.technologies,
                )
                if value
            ],
            "Certifications": [certification.name for certification in resume.certifications],
            "Education": [
                value
                for education in resume.education
                for value in (
                    education.institution,
                    education.degree or "",
                    education.program or "",
                    *education.details,
                )
                if value
            ],
        }

    def _term_in_values(self, term: str, values: Sequence[str]) -> bool:
        canonical = canonical_skill_name(term)
        return any(
            canonical_skill_name(value) == canonical
            or term.casefold() in value.casefold()
            or self._supported_phrase_variant(term, value)
            for value in values
        )

    def _supported_phrase_variant(self, term: str, value: str) -> bool:
        term_text = term.casefold()
        value_text = value.casefold()
        return (
            term_text == "network traffic analysis"
            and "network traffic" in value_text
            and "analyz" in value_text
        )

    def _soft_skill_matches(
        self,
        evidence: Sequence[str],
        soft_skills: Iterable[str],
    ) -> list[str]:
        evidence_text = " ".join(evidence).casefold()
        matches: list[str] = []
        for skill in soft_skills:
            root = canonical_skill_name(skill).split()[0][:8]
            if skill.casefold() in evidence_text or (len(root) >= 5 and root in evidence_text):
                matches.append(skill)
        return matches

    def _matching_keywords(
        self,
        evidence: Sequence[str],
        keywords: Iterable[str],
    ) -> list[str]:
        return [
            keyword
            for keyword in deduplicate_match_terms(keywords)
            if self._term_in_values(keyword, evidence)
        ]

    def _target_sections(self, evidence_sources: Sequence[str]) -> list[str]:
        known = {"Skills", "Projects", "Experience", "Certifications", "Education"}
        sections = [source for source in evidence_sources if source in known]
        return sections or ["Skills"]

    def _relevance_score(self, matches: Sequence[str], evidence_count: int) -> float:
        if not evidence_count:
            return 0.0
        return round(min(100.0, len(matches) * 25.0 + min(evidence_count * 3.0, 25.0)), 1)

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized and normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result
