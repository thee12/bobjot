import { apiRequest } from "./client";
import type { ResumeDetail, ResumeSummary, ResumeUploadResponse, ResumeVersionDetail, ResumeVersionSummary } from "../types/api";

export const uploadResume = (file: File) => {
  const body = new FormData();
  body.append("file", file);
  body.append("parse_with_llm", "true");
  return apiRequest<ResumeUploadResponse>("/resumes/upload", { method: "POST", body });
};
export const listResumes = () => apiRequest<ResumeSummary[]>("/resumes");
export const getResume = (id: string) => apiRequest<ResumeDetail>(`/resumes/${id}`);
export const listResumeVersions = (id: string) => apiRequest<ResumeVersionSummary[]>(`/resumes/${id}/versions`);
export const getResumeVersion = (id: string) => apiRequest<ResumeVersionDetail>(`/resumes/versions/${id}`);
