import { apiRequest } from "./client";
import type { PipelineRunDetail, PipelineRunRequest, PipelineRunResult, PipelineStepRecord, PipelineSubmissionResult } from "../types/api";

export const startPipelineRun = (request: PipelineRunRequest) =>
  apiRequest<PipelineSubmissionResult>("/pipeline/runs", { method: "POST", body: JSON.stringify(request) });
export const listPipelineRuns = () => apiRequest<PipelineRunDetail[]>("/pipeline/runs");
export const getPipelineRun = (id: string) => apiRequest<PipelineRunDetail>(`/pipeline/runs/${id}`);
export const getPipelineRunSteps = (id: string) => apiRequest<PipelineStepRecord[]>(`/pipeline/runs/${id}/steps`);
export const getPipelineRunResult = (id: string) => apiRequest<PipelineRunResult>(`/pipeline/runs/${id}/result`);
export const cancelPipelineRun = (id: string) => apiRequest<PipelineRunDetail>(`/pipeline/runs/${id}/cancel`, { method: "POST" });
