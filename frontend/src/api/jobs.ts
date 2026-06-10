import { apiRequest } from "./client";
import type { SavedJob } from "../types/api";

export const listSavedJobs = (query = "") => apiRequest<SavedJob[]>(`/jobs/saved${query}`);
export const getSavedJob = (id: string) => apiRequest<SavedJob>(`/jobs/saved/${id}`);
export const analyzeSavedJob = (id: string) => apiRequest<Record<string, unknown>>(`/jobs/${id}/analyze`, { method: "POST" });
