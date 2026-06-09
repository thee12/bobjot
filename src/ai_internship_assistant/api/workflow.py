"""Thin orchestration for API workflows spanning existing services."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from ai_internship_assistant.api.dependencies import ApiContainer, ExportArtifact
from ai_internship_assistant.api.schemas import (
    ExportedFileResponse,
    JobSearchRequest,
    JobSearchResponse,
    OptimizationPlanResponse,
    RunOptimizationRequest,
    RunOptimizationResponse,
)
from ai_internship_assistant.domain.models import (
    ATSMatchReport,
    CandidateProfile,
    DocxRenderOptions,
    JobAnalysis,
    PdfRenderOptions,
    ProfileGenerationResult,
    RenderedResumeFile,
    ResumeOptimizationPlan,
    ResumeOptimizationRequest,
    ResumeOutputFormat,
    ResumeRenderOptions,
    SavedJob,
    SkillGapReport,
    StoredResume,
)
from ai_internship_assistant.services.resume_generator import UnsupportedResumeFormatError


@dataclass(frozen=True)
class OptimizationArtifacts:
    """Typed intermediate artifacts shared by plan and run workflows."""

    stored: StoredResume
    saved_job: SavedJob
    profile: CandidateProfile
    analysis: JobAnalysis
    gap: SkillGapReport
    ats: ATSMatchReport
    plan: ResumeOptimizationPlan


class ApiWorkflowService:
    """Coordinate existing typed services for multi-stage HTTP operations."""

    def __init__(self, container: ApiContainer) -> None:
        self._container = container

    def profile_for_resume(self, stored: StoredResume) -> ProfileGenerationResult:
        """Generate current validation and candidate-profile views."""

        return self._container.profile_pipeline.run(stored.parsed_resume)

    def search_jobs(self, request: JobSearchRequest) -> JobSearchResponse:
        """Search configured sources, rank results, and optionally save them."""

        stored = self._container.versioning.get_master_resume(request.resume_id)
        generated = self.profile_for_resume(stored)
        preferences = request.preferences.model_copy(
            update={"max_results_per_query": request.max_results}
        )
        query_set = self._container.query_generator.generate(generated.profile, preferences)
        search = self._container.job_search.search_all(query_set)
        ranked = self._container.job_ranker.rank_jobs(
            generated.profile,
            search.jobs,
            preferences,
        )
        selected = ranked.results[: request.max_results]
        if request.save_results:
            for result in selected:
                self._container.tracking.save_job(
                    result.job,
                    fit_score=result.score.overall_score,
                )
        warnings = list(search.deduplication_result.warnings) if search.deduplication_result else []
        warnings.extend(error.message for error in search.errors)
        return JobSearchResponse(
            resume_id=request.resume_id,
            query_count=query_set.total_count,
            total_jobs_found=sum(result.total_found for result in search.source_results),
            total_unique_jobs=len(search.jobs),
            ranked_jobs=(
                [result.model_dump(mode="json") for result in selected]
                if request.include_rankings
                else [{"job": result.job.model_dump(mode="json")} for result in selected]
            ),
            warnings=warnings,
        )

    def analyze_saved_job(self, saved_job_id: str) -> JobAnalysis:
        """Analyze and persist one saved job snapshot."""

        saved = self._container.tracking.get_saved_job(saved_job_id)
        analysis = self._container.job_analyzer.analyze(saved.job_posting)
        self._container.tracking.save_job(
            saved.job_posting,
            analysis,
            saved.ats_match_report,
            fit_score=saved.fit_score,
            notes=saved.notes,
        )
        return analysis

    def optimization_artifacts(
        self,
        resume_id: str,
        saved_job_id: str,
    ) -> OptimizationArtifacts:
        """Create deterministic profile, analysis, gap, ATS, and plan artifacts."""

        stored = self._container.versioning.get_master_resume(resume_id)
        saved = self._container.tracking.get_saved_job(saved_job_id)
        profile = self.profile_for_resume(stored).profile
        analysis = saved.job_analysis or self.analyze_saved_job(saved_job_id)
        gap = self._container.gap_analyzer.analyze(profile, analysis)
        ats = self._container.ats_scorer.score(stored.parsed_resume, profile, analysis, gap)
        plan = self._container.planner.create_plan(
            stored.parsed_resume,
            profile,
            analysis,
            gap,
            ats,
        )
        return OptimizationArtifacts(stored, saved, profile, analysis, gap, ats, plan)

    def plan_optimization(self, resume_id: str, saved_job_id: str) -> OptimizationPlanResponse:
        """Create an unpersisted optimization plan response."""

        artifacts = self.optimization_artifacts(resume_id, saved_job_id)
        ats = artifacts.ats
        plan = artifacts.plan
        return OptimizationPlanResponse(
            plan_id=None,
            baseline_ats_score=ats.overall_score,
            optimization_priority=plan.optimization_priority.value,
            safe_keywords=plan.safe_keywords,
            unsafe_keywords=plan.unsafe_keywords,
            forbidden_claims=plan.forbidden_claims,
            section_plans=[item.model_dump(mode="json") for item in plan.section_plans],
            expected_score_improvement=plan.expected_score_improvement.model_dump(mode="json"),
            warnings=plan.warnings,
        )

    def run_optimization(self, request: RunOptimizationRequest) -> RunOptimizationResponse:
        """Run safe optimization, persist its version, and optionally export it."""

        artifacts = self.optimization_artifacts(
            request.resume_id,
            request.saved_job_id,
        )
        options = request.options.model_copy(update={"strict_mode": request.strict_mode})
        result = self._container.optimizer.optimize(
            ResumeOptimizationRequest(
                resume=artifacts.stored.parsed_resume,
                candidate_profile=artifacts.profile,
                job_analysis=artifacts.analysis,
                skill_gap_report=artifacts.gap,
                ats_match_report=artifacts.ats,
                optimization_plan=artifacts.plan,
                options=options,
            )
        )
        self._container.jobs.save(artifacts.saved_job.job_posting, artifacts.analysis)
        version = self._container.versioning.save_optimized_resume(
            request.resume_id,
            result,
            target_job_id=artifacts.saved_job.job_posting.id,
        )
        files = self.export_version(version.id, request.export_formats, allow_overwrite=False)
        return RunOptimizationResponse(
            resume_version_id=version.id,
            target_job_title=version.target_job_title or "",
            target_company=version.target_company or "",
            before_ats_score=version.before_ats_score,
            estimated_after_score={
                "low": version.estimated_after_score_low,
                "high": version.estimated_after_score_high,
            },
            change_count=len(version.change_log),
            safety_status="passed" if version.safety_report.passed else "failed",
            exported_files=files,
            warnings=result.warnings,
        )

    def export_version(
        self,
        version_id: str,
        formats: list[str],
        *,
        allow_overwrite: bool,
        options: dict[str, object] | None = None,
    ) -> list[ExportedFileResponse]:
        """Render stored optimized content and register safe opaque download IDs."""

        version = self._container.versioning.get_resume_version(version_id)
        exported: list[ExportedFileResponse] = []
        for requested_format in formats:
            normalized = requested_format.casefold()
            output_dir = self._container.export_dir / version.id
            output_dir.mkdir(parents=True, exist_ok=True)
            if normalized == ResumeOutputFormat.MARKDOWN.value:
                rendered = self._container.markdown_renderer.render_to_file(
                    version.optimized_resume,
                    output_dir,
                    ResumeRenderOptions(source_version_id=version.id),
                    overwrite=allow_overwrite,
                )
            elif normalized == ResumeOutputFormat.DOCX.value:
                rendered = self._container.docx_renderer.render_to_file(
                    version.optimized_resume,
                    output_dir,
                    DocxRenderOptions.model_validate(options or {}),
                    overwrite=allow_overwrite,
                )
            elif normalized == ResumeOutputFormat.PDF.value:
                rendered = self._container.pdf_renderer.render_to_file(
                    version.optimized_resume,
                    output_dir,
                    PdfRenderOptions.model_validate(options or {}),
                    overwrite=allow_overwrite,
                )
            else:
                raise UnsupportedResumeFormatError(f"unsupported export format: {requested_format}")
            exported.append(self._register_export(rendered))
        return exported

    def _register_export(self, rendered: RenderedResumeFile) -> ExportedFileResponse:
        path = Path(rendered.path).resolve()
        allowed = self._container.export_dir.resolve()
        if allowed not in path.parents:
            raise ValueError("generated export is outside the configured export directory")
        file_id = str(uuid4())
        media_types = {
            ResumeOutputFormat.MARKDOWN: "text/markdown",
            ResumeOutputFormat.DOCX: (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            ResumeOutputFormat.PDF: "application/pdf",
        }
        self._container.exports[file_id] = ExportArtifact(
            path=path,
            filename=path.name,
            media_type=media_types[rendered.format],
        )
        return ExportedFileResponse(
            file_id=file_id,
            filename=path.name,
            format=rendered.format.value,
            byte_size=rendered.byte_size,
            content_hash=rendered.content_hash or hashlib.sha256(path.read_bytes()).hexdigest(),
        )
