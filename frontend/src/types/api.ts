export type PipelineStatus =
  | "pending" | "running" | "completed" | "partial_success"
  | "failed" | "cancel_requested" | "cancelled";

export interface ResumeSummary {
  resume_id: string;
  candidate_name: string | null;
  original_filename: string | null;
  created_at: string;
  updated_at: string;
  version_count: number;
}

export interface ResumeUploadResponse {
  resume_id: string;
  candidate_name: string | null;
  validation_warnings: string[];
  candidate_profile_summary: string;
  created_at: string;
}

export interface ResumeEntry {
  full_name?: string | null;
  email?: string | null;
  phone?: string | null;
  location?: string | null;
  linkedin_url?: string | null;
  github_url?: string | null;
  summary?: string | null;
  skills: { name: string; category?: string | null }[];
  education: { institution: string; degree?: string | null; program?: string | null; end_date?: string | null; details: string[] }[];
  certifications: { name: string; issuer?: string | null; issued_date?: string | null }[];
  projects: { name: string; description?: string | null; technologies: string[]; bullets: string[] }[];
  experience: { organization: string; title: string; start_date?: string | null; end_date?: string | null; technologies: string[]; bullets: string[] }[];
}

export interface ResumeDetail {
  resume_id: string;
  candidate_name: string | null;
  parsed_resume: ResumeEntry;
  candidate_profile: {
    profile_summary: string;
    primary_domain: string;
    experience_level: string;
    confidence_score: number;
    target_roles: string[];
    core_skills: string[];
    supporting_skills: string[];
  };
  validation_report: {
    issues: { severity: string; category: string; message: string; suggestion?: string | null }[];
    warning_count: number;
    error_count: number;
    is_valid: boolean;
  };
  created_at: string;
}

export interface ResumeVersionSummary {
  id: string;
  version_name: string;
  target_job_title: string | null;
  target_company: string | null;
  before_ats_score: number;
  estimated_after_score_low: number;
  estimated_after_score_high: number;
  optimization_priority: string;
  created_at: string;
}

export interface ResumeVersionDetail extends ResumeVersionSummary {
  version_id: string;
  optimized_resume: Record<string, unknown>;
  change_log: { change_type?: string; section?: string; explanation?: string }[];
  safety_report: { passed: boolean; status?: string; violations?: unknown[]; warnings?: string[] };
}

export interface PipelineRunRequest {
  resume_id: string;
  execution_mode: "synchronous" | "local_background";
  preferences: {
    desired_roles: string[];
    desired_locations: string[];
    employment_types: string[];
  };
  max_jobs_to_search: number;
  max_jobs_to_analyze: number;
  max_jobs_to_optimize: number;
  optimization_enabled: boolean;
  export_enabled: boolean;
  export_formats: string[];
  create_applications: boolean;
}

export interface PipelineSubmissionResult {
  pipeline_run_id: string;
  status: PipelineStatus;
  execution_mode: string;
  polling_url: string;
  result_url: string;
  submitted_at: string;
}

export interface PipelineRunDetail {
  id: string;
  resume_id: string;
  status: PipelineStatus;
  current_step: string | null;
  progress_percentage: number;
  warning_count: number;
  error_count: number;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
  duration_seconds: number | null;
  execution_mode: string;
  cancellation_requested: boolean;
}

export interface PipelineStepRecord {
  id: string;
  step: string;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  duration_seconds: number | null;
  warning_count: number;
  error_count: number;
}

export interface PipelineRunResult {
  resume_id: string;
  jobs_found: number;
  saved_job_ids: string[];
  analyzed_job_ids: string[];
  resume_version_ids: string[];
  export_file_ids: string[];
  application_ids: string[];
  warnings: string[];
  errors: string[];
}

export interface SavedJob {
  id: string;
  title: string;
  company: string;
  location: string | null;
  source: string;
  apply_url: string | null;
  fit_score: number | null;
  ats_score: number | null;
  saved_at: string;
  is_active: boolean;
  notes: string | null;
  job: {
    description: string | null;
    technologies: string[];
    requirements: string[];
    preferred_qualifications: string[];
  };
  job_analysis: Record<string, unknown> | null;
}

export interface ApplicationSummary {
  id: string;
  saved_job_id: string;
  title: string;
  company: string;
  status: string;
  applied_at: string | null;
  follow_up_date: string | null;
  resume_version_id: string | null;
  ats_score: number | null;
  fit_score: number | null;
  latest_note: string | null;
  updated_at: string;
}

export interface ApplicationDetail {
  application: {
    id: string; saved_job_id: string; resume_version_id: string | null; status: string;
    applied_at: string | null; follow_up_date: string | null; notes: string | null; updated_at: string;
  };
  saved_job: SavedJob;
  notes: { id: string; note: string; note_type: string; created_at: string }[];
  status_history: { id: string; old_status: string | null; new_status: string; changed_at: string; note: string | null }[];
}

export interface ExportedFile {
  file_id: string;
  filename: string;
  format: string;
  byte_size: number;
  content_hash: string;
}
