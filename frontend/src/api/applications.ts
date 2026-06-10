import { apiRequest } from "./client";
import type { ApplicationDetail, ApplicationSummary } from "../types/api";

export const listApplications = (query = "") => apiRequest<ApplicationSummary[]>(`/applications${query}`);
export const getApplication = (id: string) => apiRequest<ApplicationDetail>(`/applications/${id}`);
export const createApplication = (savedJobId: string, versionId?: string) =>
  apiRequest(`/applications`, { method: "POST", body: JSON.stringify({ saved_job_id: savedJobId, resume_version_id: versionId }) });
export const updateApplicationStatus = (id: string, status: string, note?: string) =>
  apiRequest(`/applications/${id}/status`, { method: "PATCH", body: JSON.stringify({ status, note }) });
export const addApplicationNote = (id: string, note: string, noteType = "general") =>
  apiRequest(`/applications/${id}/notes`, { method: "POST", body: JSON.stringify({ note, note_type: noteType }) });
export const setFollowUp = (id: string, followUpDate: string | null) =>
  apiRequest(`/applications/${id}/follow-up`, { method: "PATCH", body: JSON.stringify({ follow_up_date: followUpDate }) });
