"""Resume optimization planning and execution endpoints."""

from fastapi import APIRouter

from ai_internship_assistant.api.dependencies import ContainerDependency
from ai_internship_assistant.api.schemas import (
    OptimizationPlanRequest,
    OptimizationPlanResponse,
    RunOptimizationRequest,
    RunOptimizationResponse,
)
from ai_internship_assistant.api.workflow import ApiWorkflowService

router = APIRouter(prefix="/optimization", tags=["optimization"])


@router.post("/plan", response_model=OptimizationPlanResponse)
def create_plan(
    request: OptimizationPlanRequest,
    container: ContainerDependency,
) -> OptimizationPlanResponse:
    """Create an evidence-backed optimization plan without persisting it."""

    return ApiWorkflowService(container).plan_optimization(request.resume_id, request.saved_job_id)


@router.post("/run", response_model=RunOptimizationResponse)
def run_optimization(
    request: RunOptimizationRequest,
    container: ContainerDependency,
) -> RunOptimizationResponse:
    """Create and persist a safe optimized resume version."""

    # TODO: move optimization and multi-format export to a background task.
    return ApiWorkflowService(container).run_optimization(request)
