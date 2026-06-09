"""Deterministic full-resume assembly guarded by an optimization safety plan."""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Sequence

from ai_internship_assistant.domain.models import (
    BulletRewriteRequest,
    BulletRewriteResult,
    CandidateProfile,
    ChangeType,
    ExpectedScoreImprovement,
    Experience,
    OptimizedResume,
    OptimizedResumeContact,
    OptimizedResumeMetadata,
    OptimizedResumeResult,
    Project,
    Resume,
    ResumeChange,
    ResumeOptimizationOptions,
    ResumeOptimizationPlan,
    ResumeOptimizationRequest,
    ResumeOptimizationSafetyReport,
    SafetyStatus,
    Skill,
)
from ai_internship_assistant.services.resume_bullet_rewriter import (
    BulletRewriteSafetyValidator,
    ResumeBulletRewriter,
    build_bullet_rewrite_request,
)
from ai_internship_assistant.utils import canonical_skill_name, deduplicate_match_terms

_OPTIMIZER_VERSION = "full-resume-optimizer-v1"
_METRIC_PATTERN = re.compile(
    r"(?:\$\s?\d[\d,.]*|\b\d+(?:\.\d+)?%|\b\d+\+?\s+"
    r"(?:users?|customers?|tickets?|requests?|systems?|servers?|hours?|days?|weeks?)\b)",
    re.IGNORECASE,
)


class FullResumeOptimizationError(TypeError):
    """Raised when optimizer inputs violate the programming contract."""


class FullResumeOptimizer:
    """Assemble a complete tailored resume from deterministic plans and safe rewrites.

    The optimizer never performs a freeform full-resume rewrite. It copies source
    facts, applies bounded ordering and trimming decisions, and sends only individual
    bullets through the injected provider-neutral ``ResumeBulletRewriter``.
    """

    def __init__(
        self,
        bullet_rewriter: ResumeBulletRewriter,
        *,
        safety_validator: BulletRewriteSafetyValidator | None = None,
    ) -> None:
        """Create an optimizer with an explicit single-bullet rewrite boundary."""

        self._bullet_rewriter = bullet_rewriter
        self._bullet_validator = safety_validator or BulletRewriteSafetyValidator()

    def optimize(self, request: ResumeOptimizationRequest) -> OptimizedResumeResult:
        """Build a safe tailored resume without mutating any input model."""

        self._validate_request(request)
        resume = request.resume
        plan = request.optimization_plan
        options = request.options
        changes: list[ResumeChange] = []
        skipped: list[ResumeChange] = []
        warnings = list(plan.warnings)

        skills = self._skills(resume, plan, options, changes, skipped)
        projects = self._projects(resume, plan, options, changes, skipped, warnings)
        experience = self._experience(resume, plan, options, changes, skipped, warnings)
        summary = self._summary(request, changes, skipped)
        section_order = self._section_order(request, projects, changes)
        optimized = self._optimized_resume(
            request,
            summary=summary,
            skills=skills,
            projects=projects,
            experience=experience,
            section_order=section_order,
        )
        safety = self._final_safety_audit(resume, optimized, plan, skipped)
        if options.strict_mode and (not safety.passed or safety.blocked_changes):
            warnings.append("Strict mode returned the original resume after a safety violation.")
            optimized = self._original_as_optimized(request)
            changes = []
        estimate = self._estimated_score(plan, changes, safety)
        return OptimizedResumeResult(
            original_resume=resume.model_copy(deep=True),
            optimized_resume=optimized,
            optimization_plan=plan.model_copy(deep=True),
            skill_gap_report=request.skill_gap_report.model_copy(deep=True),
            ats_match_report=request.ats_match_report.model_copy(deep=True),
            changes=changes,
            skipped_changes=skipped,
            safety_report=safety,
            before_ats_score=request.ats_match_report.overall_score,
            estimated_after_ats_score=estimate,
            optimization_plan_id=self._plan_id(plan),
            warnings=self._deduplicate(warnings),
            optimizer_version=_OPTIMIZER_VERSION,
        )

    def _validate_request(self, request: ResumeOptimizationRequest) -> None:
        if not isinstance(request, ResumeOptimizationRequest):
            raise FullResumeOptimizationError("request must be a ResumeOptimizationRequest")
        identifiers = {
            request.job_analysis.job_id,
            request.skill_gap_report.job_id,
            request.ats_match_report.job_id,
            request.optimization_plan.job_id,
        }
        if len(identifiers) != 1:
            raise FullResumeOptimizationError("job IDs must match across optimization inputs")
        plan = request.optimization_plan
        if (
            plan.target_job_title != request.job_analysis.job_title
            or plan.target_company != request.job_analysis.company
        ):
            raise FullResumeOptimizationError("optimization plan target must match job analysis")

    def _skills(
        self,
        resume: Resume,
        plan: ResumeOptimizationPlan,
        options: ResumeOptimizationOptions,
        changes: list[ResumeChange],
        skipped: list[ResumeChange],
    ) -> list[Skill]:
        original = list(resume.skills)
        if not options.enable_skill_reordering or options.preserve_original_order:
            return [skill.model_copy(deep=True) for skill in original]
        by_name = {canonical_skill_name(skill.name): skill for skill in original}
        ordered: list[Skill] = []
        for name in plan.skill_reordering_plan.recommended_order:
            skill = by_name.get(canonical_skill_name(name))
            if skill and skill not in ordered:
                ordered.append(skill)
            elif not skill:
                skipped.append(
                    self._change(
                        ChangeType.SKILL_REORDERED,
                        "Skills",
                        name,
                        None,
                        name,
                        "Blocked a planned skill absent from the source resume.",
                        [],
                        SafetyStatus.BLOCKED,
                    )
                )
        ordered.extend(skill for skill in original if skill not in ordered)
        if [skill.name for skill in ordered] != [skill.name for skill in original]:
            changes.append(
                self._change(
                    ChangeType.SKILL_REORDERED,
                    "Skills",
                    None,
                    [skill.name for skill in original],
                    [skill.name for skill in ordered],
                    plan.skill_reordering_plan.rationale,
                    plan.safe_keywords,
                    SafetyStatus.SAFE,
                )
            )
        return [skill.model_copy(deep=True) for skill in ordered]

    def _projects(
        self,
        resume: Resume,
        plan: ResumeOptimizationPlan,
        options: ResumeOptimizationOptions,
        changes: list[ResumeChange],
        skipped: list[ResumeChange],
        warnings: list[str],
    ) -> list[Project]:
        original = list(resume.projects)
        plans = {item.project_name.casefold(): item for item in plan.project_emphasis_plan}
        ordered = self._ordered_projects(original, plan, options)
        if [item.name for item in ordered] != [item.name for item in original]:
            changes.append(
                self._change(
                    ChangeType.PROJECT_REORDERED,
                    "Projects",
                    None,
                    [item.name for item in original],
                    [item.name for item in ordered],
                    "Placed evidence-backed, job-relevant projects first.",
                    plan.safe_keywords,
                    SafetyStatus.SAFE,
                )
            )
        kept, removed = ordered[: options.max_projects], ordered[options.max_projects :]
        self._record_section_trim("Projects", removed, changes)
        result: list[Project] = []
        for project in kept:
            project_plan = plans.get(project.name.casefold())
            bullets = self._optimize_bullets(
                project.bullets,
                "Projects",
                project.name,
                project_plan.candidate_evidence if project_plan else [project.name],
                project_plan.related_job_keywords if project_plan else [],
                plan,
                options.max_bullets_per_project,
                options,
                changes,
                skipped,
                warnings,
            )
            result.append(project.model_copy(update={"bullets": bullets}, deep=True))
        return result

    def _experience(
        self,
        resume: Resume,
        plan: ResumeOptimizationPlan,
        options: ResumeOptimizationOptions,
        changes: list[ResumeChange],
        skipped: list[ResumeChange],
        warnings: list[str],
    ) -> list[Experience]:
        original = list(resume.experience)
        plans = {item.experience_name.casefold(): item for item in plan.experience_emphasis_plan}
        ordered = self._ordered_experience(original, plan, options)
        if [self._experience_name(item) for item in ordered] != [
            self._experience_name(item) for item in original
        ]:
            changes.append(
                self._change(
                    ChangeType.EXPERIENCE_REORDERED,
                    "Experience",
                    None,
                    [self._experience_name(item) for item in original],
                    [self._experience_name(item) for item in ordered],
                    "Placed evidence-backed, job-relevant experience first.",
                    plan.safe_keywords,
                    SafetyStatus.SAFE,
                )
            )
        kept, removed = ordered[: options.max_experiences], ordered[options.max_experiences :]
        self._record_section_trim("Experience", removed, changes)
        result: list[Experience] = []
        for item in kept:
            name = self._experience_name(item)
            item_plan = plans.get(name.casefold())
            bullets = self._optimize_bullets(
                item.bullets,
                "Experience",
                name,
                item_plan.candidate_evidence if item_plan else [name],
                item_plan.related_job_keywords if item_plan else [],
                plan,
                options.max_bullets_per_experience,
                options,
                changes,
                skipped,
                warnings,
            )
            result.append(item.model_copy(update={"bullets": bullets}, deep=True))
        return result

    def _optimize_bullets(
        self,
        bullets: Sequence[str],
        section: str,
        item_name: str,
        evidence: Sequence[str],
        related_keywords: Sequence[str],
        plan: ResumeOptimizationPlan,
        limit: int,
        options: ResumeOptimizationOptions,
        changes: list[ResumeChange],
        skipped: list[ResumeChange],
        warnings: list[str],
    ) -> list[str]:
        kept, removed = list(bullets[:limit]), list(bullets[limit:])
        for bullet in removed:
            changes.append(
                self._change(
                    ChangeType.BULLET_REMOVED,
                    section,
                    item_name,
                    bullet,
                    None,
                    "Removed to satisfy configured resume length constraints.",
                    [],
                    SafetyStatus.SAFE,
                )
            )
        if not options.enable_bullet_rewrites:
            return kept
        result: list[str] = []
        for bullet in kept:
            rewrite_request = build_bullet_rewrite_request(
                original_bullet=bullet,
                section_name=section,
                parent_item_name=item_name,
                candidate_evidence=evidence,
                plan=plan,
                max_length=options.maximum_bullet_length,
                optimization_goal=(
                    "Improve target-job relevance using only supported terms: "
                    f"{', '.join(related_keywords)}"
                ),
            )
            try:
                rewrite = self._bullet_rewriter.rewrite(rewrite_request)
            except Exception as exc:  # Provider adapters may expose implementation-specific errors.
                warnings.append(f"Bullet rewrite failed for {item_name}: {exc}")
                rewrite = None
            accepted = self._accept_rewrite(rewrite_request, rewrite)
            if rewrite is None or not accepted:
                reason = (
                    "Bullet rewriter failed; preserved the original bullet."
                    if rewrite is None
                    else "Rejected an unsafe bullet rewrite and preserved the original."
                )
                skipped.append(
                    self._change(
                        ChangeType.BULLET_REWRITTEN,
                        section,
                        item_name,
                        bullet,
                        rewrite.rewritten_bullet if rewrite else None,
                        reason,
                        list(evidence),
                        SafetyStatus.BLOCKED,
                    )
                )
                result.append(bullet)
            elif rewrite.changed:
                result.append(rewrite.rewritten_bullet)
                changes.append(
                    self._change(
                        ChangeType.BULLET_REWRITTEN,
                        section,
                        item_name,
                        bullet,
                        rewrite.rewritten_bullet,
                        rewrite.explanation,
                        [*evidence, *rewrite.included_keywords],
                        SafetyStatus.SAFE,
                    )
                )
            else:
                result.append(bullet)
                changes.append(
                    self._change(
                        ChangeType.BULLET_UNCHANGED,
                        section,
                        item_name,
                        bullet,
                        bullet,
                        rewrite.explanation,
                        list(evidence),
                        SafetyStatus.SAFE,
                    )
                )
        return result

    def _accept_rewrite(
        self,
        request: BulletRewriteRequest,
        rewrite: BulletRewriteResult | None,
    ) -> bool:
        if rewrite is None:
            return False
        if rewrite.safety_violations:
            return False
        return not self._bullet_validator.validate(request, rewrite.rewritten_bullet)

    def _summary(
        self,
        request: ResumeOptimizationRequest,
        changes: list[ResumeChange],
        skipped: list[ResumeChange],
    ) -> str | None:
        original = request.resume.summary
        options = request.options
        if not options.include_summary:
            return original
        if options.strict_mode and not original:
            skipped.append(
                self._change(
                    ChangeType.SUMMARY_ADDED,
                    "Summary",
                    None,
                    None,
                    None,
                    "Strict mode does not add a summary absent from the original resume.",
                    [],
                    SafetyStatus.WARNING,
                )
            )
            return None
        summary = self._factual_summary(request.candidate_profile, request.optimization_plan)
        if not summary:
            return original
        change_type = ChangeType.SUMMARY_UPDATED if original else ChangeType.SUMMARY_ADDED
        changes.append(
            self._change(
                change_type,
                "Summary",
                None,
                original,
                summary,
                "Created a concise summary from candidate-profile and source-supported keywords.",
                request.optimization_plan.safe_keywords,
                SafetyStatus.SAFE,
            )
        )
        return summary

    def _factual_summary(
        self,
        profile: CandidateProfile,
        plan: ResumeOptimizationPlan,
    ) -> str | None:
        profile_terms = {
            canonical_skill_name(value)
            for value in [*profile.core_skills, *profile.supporting_skills, *profile.technologies]
        }
        skills = [
            keyword
            for keyword in plan.safe_keywords
            if canonical_skill_name(keyword) in profile_terms
        ][:4]
        identity = profile.education_level or profile.primary_domain.value
        if not identity and not skills:
            return None
        skill_phrase = f" with knowledge of {', '.join(skills)}" if skills else ""
        return f"{identity}{skill_phrase}, seeking {plan.target_job_title} opportunities."

    def _section_order(
        self,
        request: ResumeOptimizationRequest,
        projects: Sequence[Project],
        changes: list[ResumeChange],
    ) -> list[str]:
        default = [
            "Contact",
            "Education",
            "Certifications",
            "Skills",
            "Projects",
            "Experience",
            "Additional Sections",
        ]
        options = request.options
        if not options.enable_section_reordering or options.preserve_original_order:
            return default
        matched_certifications = bool(request.ats_match_report.matched_certifications)
        relevant_project = bool(
            projects
            and request.optimization_plan.project_emphasis_plan
            and request.optimization_plan.project_emphasis_plan[0].relevance_score >= 50
        )
        order = list(default)
        if relevant_project and not matched_certifications:
            order.remove("Projects")
            order.insert(order.index("Certifications"), "Projects")
        if order != default:
            changes.append(
                self._change(
                    ChangeType.SECTION_REORDERED,
                    "Resume",
                    None,
                    default,
                    order,
                    "Placed the strongest supported section earlier for the target role.",
                    request.optimization_plan.safe_keywords,
                    SafetyStatus.SAFE,
                )
            )
        return order

    def _optimized_resume(
        self,
        request: ResumeOptimizationRequest,
        *,
        summary: str | None,
        skills: list[Skill],
        projects: list[Project],
        experience: list[Experience],
        section_order: list[str],
    ) -> OptimizedResume:
        resume = request.resume
        return OptimizedResume(
            contact=self._contact(resume),
            summary=summary,
            education=[item.model_copy(deep=True) for item in resume.education],
            certifications=[item.model_copy(deep=True) for item in resume.certifications],
            skills=skills,
            projects=projects,
            experience=experience,
            target_job_title=request.optimization_plan.target_job_title,
            target_company=request.optimization_plan.target_company,
            metadata=OptimizedResumeMetadata(
                job_id=request.optimization_plan.job_id,
                source_resume_hash=self._resume_hash(resume),
                section_order=section_order,
                target_format=request.options.target_format,
                max_pages=request.options.max_pages,
            ),
        )

    def _original_as_optimized(self, request: ResumeOptimizationRequest) -> OptimizedResume:
        return self._optimized_resume(
            request,
            summary=request.resume.summary,
            skills=[item.model_copy(deep=True) for item in request.resume.skills],
            projects=[item.model_copy(deep=True) for item in request.resume.projects],
            experience=[item.model_copy(deep=True) for item in request.resume.experience],
            section_order=[
                "Contact",
                "Education",
                "Certifications",
                "Skills",
                "Projects",
                "Experience",
                "Additional Sections",
            ],
        )

    def _final_safety_audit(
        self,
        original: Resume,
        optimized: OptimizedResume,
        plan: ResumeOptimizationPlan,
        skipped: Sequence[ResumeChange],
    ) -> ResumeOptimizationSafetyReport:
        original_text = self._resume_content_text(original)
        optimized_text = self._optimized_content_text(optimized)
        unsafe = self._new_terms(original_text, optimized_text, plan.unsafe_keywords)
        forbidden = self._new_terms(original_text, optimized_text, plan.forbidden_claims)
        invented_metrics = self._new_metrics(original_text, optimized_text)
        invented_technologies = self._invented_technologies(original, optimized)
        warnings: list[str] = []
        if unsafe:
            warnings.append("Optimized resume introduced unsafe keywords.")
        if forbidden:
            warnings.append("Optimized resume introduced forbidden claims.")
        if invented_metrics:
            warnings.append("Optimized resume introduced unsupported metrics.")
        if invented_technologies:
            warnings.append("Optimized resume introduced unsupported technologies.")
        blocked = [item for item in skipped if item.safety_status == SafetyStatus.BLOCKED]
        passed = not any([unsafe, forbidden, invented_metrics, invented_technologies])
        return ResumeOptimizationSafetyReport(
            passed=passed,
            blocked_changes=blocked,
            unsafe_keywords_detected=unsafe,
            forbidden_claims_detected=forbidden,
            invented_technologies_detected=invented_technologies,
            invented_metrics_detected=invented_metrics,
            warnings=warnings,
            notes=[
                "Employers, roles, dates, education, certifications, and structured "
                "technology lists are copied from the source resume."
            ],
        )

    def _invented_technologies(
        self,
        original: Resume,
        optimized: OptimizedResume,
    ) -> list[str]:
        source = {
            canonical_skill_name(value)
            for value in [
                *(skill.name for skill in original.skills),
                *(
                    technology
                    for project in original.projects
                    for technology in project.technologies
                ),
                *(
                    technology
                    for experience in original.experience
                    for technology in experience.technologies
                ),
            ]
        }
        result: list[str] = []
        for value in [
            *(skill.name for skill in optimized.skills),
            *(technology for project in optimized.projects for technology in project.technologies),
            *(
                technology
                for experience in optimized.experience
                for technology in experience.technologies
            ),
        ]:
            if canonical_skill_name(value) not in source:
                result.append(value)
        return deduplicate_match_terms(result)

    def _estimated_score(
        self,
        plan: ResumeOptimizationPlan,
        changes: Sequence[ResumeChange],
        safety: ResumeOptimizationSafetyReport,
    ) -> ExpectedScoreImprovement:
        if not safety.passed:
            return ExpectedScoreImprovement(
                low=0.0,
                high=0.0,
                rationale="No improvement is estimated because safety checks blocked changes.",
            )
        meaningful = sum(
            item.change_type
            in {
                ChangeType.SKILL_REORDERED,
                ChangeType.PROJECT_REORDERED,
                ChangeType.EXPERIENCE_REORDERED,
                ChangeType.BULLET_REWRITTEN,
                ChangeType.SUMMARY_ADDED,
                ChangeType.SUMMARY_UPDATED,
            }
            for item in changes
        )
        scale = min(1.0, meaningful / 5) if meaningful else 0.0
        return ExpectedScoreImprovement(
            low=round(plan.expected_score_improvement.low * scale, 1),
            high=round(plan.expected_score_improvement.high * scale, 1),
            rationale=(
                "Estimate scales the planning range by completed safe changes and remains "
                "limited by unsupported missing skills. It is not a guaranteed ATS outcome."
            ),
        )

    def _ordered_projects(
        self,
        projects: Sequence[Project],
        plan: ResumeOptimizationPlan,
        options: ResumeOptimizationOptions,
    ) -> list[Project]:
        if options.preserve_original_order or not options.enable_section_reordering:
            return list(projects)
        scores = {
            item.project_name.casefold(): item.relevance_score
            for item in plan.project_emphasis_plan
        }
        return sorted(
            projects,
            key=lambda item: (-scores.get(item.name.casefold(), 0.0), projects.index(item)),
        )

    def _ordered_experience(
        self,
        experience: Sequence[Experience],
        plan: ResumeOptimizationPlan,
        options: ResumeOptimizationOptions,
    ) -> list[Experience]:
        if options.preserve_original_order or not options.enable_section_reordering:
            return list(experience)
        scores = {
            item.experience_name.casefold(): item.relevance_score
            for item in plan.experience_emphasis_plan
        }
        return sorted(
            experience,
            key=lambda item: (
                -scores.get(self._experience_name(item).casefold(), 0.0),
                experience.index(item),
            ),
        )

    def _record_section_trim(
        self,
        section: str,
        removed: Sequence[Project | Experience],
        changes: list[ResumeChange],
    ) -> None:
        if removed:
            names = [
                item.name if isinstance(item, Project) else self._experience_name(item)
                for item in removed
            ]
            changes.append(
                self._change(
                    ChangeType.SECTION_TRIMMED,
                    section,
                    None,
                    names,
                    None,
                    "Trimmed lower-priority entries to satisfy configured length constraints.",
                    [],
                    SafetyStatus.SAFE,
                )
            )

    def _contact(self, resume: Resume) -> OptimizedResumeContact:
        return OptimizedResumeContact(
            source_file=resume.source_file,
            full_name=resume.full_name,
            email=resume.email,
            phone=resume.phone,
            location=resume.location,
            linkedin_url=resume.linkedin_url,
            github_url=resume.github_url,
            links=list(resume.links),
        )

    def _change(
        self,
        change_type: ChangeType,
        section: str,
        item_name: str | None,
        original: str | list[str] | None,
        new: str | list[str] | None,
        reason: str,
        evidence: Sequence[str],
        status: SafetyStatus,
    ) -> ResumeChange:
        return ResumeChange(
            change_type=change_type,
            section_name=section,
            item_name=item_name,
            original_value=original,
            new_value=new,
            reason=reason,
            evidence=list(evidence),
            safety_status=status,
        )

    def _new_terms(self, original: str, optimized: str, terms: Iterable[str]) -> list[str]:
        return [
            term
            for term in terms
            if optimized.casefold().count(term.casefold())
            > original.casefold().count(term.casefold())
        ]

    def _new_metrics(self, original: str, optimized: str) -> list[str]:
        original_counts = Counter(
            match.group(0).casefold() for match in _METRIC_PATTERN.finditer(original)
        )
        optimized_counts = Counter(
            match.group(0).casefold() for match in _METRIC_PATTERN.finditer(optimized)
        )
        return [
            metric
            for metric, count in optimized_counts.items()
            if count > original_counts.get(metric, 0)
        ]

    def _resume_text(self, resume: Resume) -> str:
        return json.dumps(resume.model_dump(mode="json"), sort_keys=True)

    def _resume_content_text(self, resume: Resume) -> str:
        return json.dumps(
            resume.model_dump(mode="json", exclude={"source_file"}),
            sort_keys=True,
        )

    def _optimized_content_text(self, resume: OptimizedResume) -> str:
        return json.dumps(
            resume.model_dump(
                mode="json",
                exclude={
                    "metadata": True,
                    "target_job_title": True,
                    "target_company": True,
                    "contact": {"source_file"},
                },
            ),
            sort_keys=True,
        )

    def _resume_hash(self, resume: Resume) -> str:
        return hashlib.sha256(self._resume_text(resume).encode()).hexdigest()

    def _plan_id(self, plan: ResumeOptimizationPlan) -> str:
        payload = json.dumps(plan.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def _experience_name(self, item: Experience) -> str:
        return f"{item.title} at {item.organization}"

    def _deduplicate(self, values: Iterable[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result
