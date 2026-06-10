import { useMutation, useQuery } from "@tanstack/react-query";
import { Ban, CheckCircle2, Circle, Clock3, Play, XCircle } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { cancelPipelineRun, getPipelineRun, getPipelineRunResult, getPipelineRunSteps, listPipelineRuns, startPipelineRun } from "../api/pipeline";
import { listResumes } from "../api/resumes";
import { EmptyState, ErrorBanner, Loading, Metric, PageHeader, Section, StatusBadge } from "../components/common/Ui";
import type { PipelineRunRequest, PipelineStatus } from "../types/api";
import { formatDateTime, titleCase } from "../utils/formatting";

const terminal: PipelineStatus[] = ["completed", "partial_success", "failed", "cancelled"];
const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

export function PipelinePage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: listResumes });
  const runs = useQuery({ queryKey: ["pipeline-runs"], queryFn: listPipelineRuns });
  const [resumeId, setResumeId] = useState(searchParams.get("resume") || "");
  const [roles, setRoles] = useState("Cybersecurity Intern, SOC Analyst Intern, Security Operations Intern");
  const [locations, setLocations] = useState("Raleigh, NC, Remote");
  const [maxSearch, setMaxSearch] = useState(50);
  const [maxAnalyze, setMaxAnalyze] = useState(10);
  const [maxOptimize, setMaxOptimize] = useState(3);
  const [exports, setExports] = useState(["docx", "pdf"]);
  const [createApplications, setCreateApplications] = useState(false);
  const [formError, setFormError] = useState("");
  const submit = useMutation({ mutationFn: startPipelineRun, onSuccess: (data) => navigate(`/pipeline/runs/${data.pipeline_run_id}`) });
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (!resumeId) return setFormError("Select a resume.");
    if (maxOptimize > maxAnalyze) return setFormError("Jobs to optimize cannot exceed jobs to analyze.");
    if (!exports.length) return setFormError("Choose at least one export format.");
    setFormError("");
    const request: PipelineRunRequest = {
      resume_id: resumeId, execution_mode: "local_background",
      preferences: { desired_roles: split(roles), desired_locations: split(locations), employment_types: ["internship"] },
      max_jobs_to_search: maxSearch, max_jobs_to_analyze: maxAnalyze, max_jobs_to_optimize: maxOptimize,
      optimization_enabled: true, export_enabled: true, export_formats: exports, create_applications: createApplications,
    };
    submit.mutate(request);
  };
  return <div className="page">
    <PageHeader title="Pipeline" description="Configure one search, analysis, optimization, and export workflow." />
    <div className="pipeline-layout"><Section title="New pipeline run">
      <form className="form-grid" onSubmit={onSubmit}>
        <label className="span-2">Master resume<select value={resumeId} onChange={(event) => setResumeId(event.target.value)}><option value="">Select a resume</option>{resumes.data?.map((resume) => <option key={resume.resume_id} value={resume.resume_id}>{resume.candidate_name || resume.original_filename}</option>)}</select></label>
        <label className="span-2">Desired roles<input value={roles} onChange={(event) => setRoles(event.target.value)} /></label>
        <label className="span-2">Desired locations<input value={locations} onChange={(event) => setLocations(event.target.value)} /></label>
        <label>Jobs to search<input type="number" min="1" max="100" value={maxSearch} onChange={(event) => setMaxSearch(Number(event.target.value))} /></label>
        <label>Jobs to analyze<input type="number" min="0" max="100" value={maxAnalyze} onChange={(event) => setMaxAnalyze(Number(event.target.value))} /></label>
        <label>Jobs to optimize<input type="number" min="0" max="20" value={maxOptimize} onChange={(event) => setMaxOptimize(Number(event.target.value))} /></label>
        <fieldset className="span-2"><legend>Export formats</legend><div className="check-row">{["docx", "pdf", "markdown"].map((format) => <label key={format}><input type="checkbox" checked={exports.includes(format)} onChange={() => setExports((current) => current.includes(format) ? current.filter((item) => item !== format) : [...current, format])} /> {format.toUpperCase()}</label>)}</div></fieldset>
        <label className="toggle-row span-2"><input type="checkbox" checked={createApplications} onChange={(event) => setCreateApplications(event.target.checked)} /><span>Create planned application records</span></label>
        {formError && <div className="field-error span-2" role="alert">{formError}</div>}
        {submit.error && <div className="span-2"><ErrorBanner error={submit.error} /></div>}
        <button className="button primary span-2" disabled={submit.isPending} type="submit"><Play size={17} /> {submit.isPending ? "Submitting..." : "Start background run"}</button>
      </form>
    </Section>
    <Section title="Recent runs">{runs.data?.length ? <div className="compact-list">{runs.data.slice(0, 8).map((run) => <Link key={run.id} to={`/pipeline/runs/${run.id}`}><span><strong>{titleCase(run.current_step || "pipeline run")}</strong><small>{run.progress_percentage}% · {formatDateTime(run.created_at)}</small></span><StatusBadge status={run.status} /></Link>)}</div> : <EmptyState title="No pipeline runs" body="Configure and start the first run." />}</Section></div>
  </div>;
}

export function PipelineRunPage() {
  const { pipelineRunId = "" } = useParams();
  const run = useQuery({ queryKey: ["pipeline-run", pipelineRunId], queryFn: () => getPipelineRun(pipelineRunId), refetchInterval: (query) => terminal.includes(query.state.data?.status as PipelineStatus) ? false : 2000 });
  const steps = useQuery({ queryKey: ["pipeline-steps", pipelineRunId], queryFn: () => getPipelineRunSteps(pipelineRunId), refetchInterval: terminal.includes(run.data?.status as PipelineStatus) ? false : 2000 });
  const result = useQuery({ queryKey: ["pipeline-result", pipelineRunId], queryFn: () => getPipelineRunResult(pipelineRunId), enabled: terminal.includes(run.data?.status as PipelineStatus) });
  const cancel = useMutation({ mutationFn: () => cancelPipelineRun(pipelineRunId), onSuccess: () => run.refetch() });
  if (run.isLoading) return <div className="page"><Loading label="Loading pipeline run" /></div>;
  if (run.error || !run.data) return <div className="page"><ErrorBanner error={run.error} /></div>;
  const active = ["pending", "running", "cancel_requested"].includes(run.data.status);
  return <div className="page"><PageHeader title="Pipeline run" description={`Submitted ${formatDateTime(run.data.created_at)}`} action={active ? <button className="button danger" onClick={() => cancel.mutate()}><Ban size={17} /> Cancel run</button> : <StatusBadge status={run.data.status} />} />
    <div className="progress-panel"><div><span>{titleCase(run.data.current_step || run.data.status)}</span><strong>{run.data.progress_percentage}%</strong></div><div className="progress-track"><i style={{ width: `${run.data.progress_percentage}%` }} /></div></div>
    <div className="metrics-grid"><Metric label="Status" value={<StatusBadge status={run.data.status} />} /><Metric label="Warnings" value={run.data.warning_count} /><Metric label="Errors" value={run.data.error_count} /><Metric label="Duration" value={run.data.duration_seconds == null ? "In progress" : `${run.data.duration_seconds.toFixed(1)}s`} /></div>
    <Section title="Steps">{steps.isLoading ? <Loading /> : <div className="step-list">{steps.data?.map((step) => <div key={step.id}>{step.status === "completed" ? <CheckCircle2 className="step-complete" size={19} /> : step.status === "failed" ? <XCircle className="step-failed" size={19} /> : step.status === "running" ? <Clock3 className="step-running" size={19} /> : <Circle size={19} />}<span className="grow"><strong>{titleCase(step.step)}</strong><small>{step.duration_seconds == null ? titleCase(step.status) : `${titleCase(step.status)} · ${step.duration_seconds.toFixed(2)}s`}</small></span>{(step.warning_count > 0 || step.error_count > 0) && <small>{step.warning_count} warnings · {step.error_count} errors</small>}</div>)}</div>}</Section>
    {result.data && "jobs_found" in result.data && <Section title="Run result"><div className="metrics-grid compact"><Metric label="Jobs found" value={result.data.jobs_found} /><Metric label="Analyzed" value={result.data.analyzed_job_ids.length} /><Metric label="Resume versions" value={result.data.resume_version_ids.length} /><Metric label="Applications" value={result.data.application_ids.length} /></div><div className="result-links"><Link className="button secondary" to="/jobs">View saved jobs</Link>{result.data.resume_version_ids.map((id) => <Link className="button secondary" key={id} to={`/resume-versions/${id}`}>View optimized resume</Link>)}</div>{result.data.warnings.map((warning) => <p className="notice-text" key={warning}>{warning}</p>)}</Section>}
  </div>;
}
