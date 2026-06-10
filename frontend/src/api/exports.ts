import { API_BASE_URL, apiRequest } from "./client";
import type { ExportedFile } from "../types/api";

export const exportResumeVersion = (id: string, formats: string[]) =>
  apiRequest<{ version_id: string; exported_files: ExportedFile[] }>(`/exports/resume-version/${id}`, {
    method: "POST", body: JSON.stringify({ formats }),
  });
export const getExportDownloadUrl = (fileId: string) => `${API_BASE_URL}/exports/files/${fileId}`;
