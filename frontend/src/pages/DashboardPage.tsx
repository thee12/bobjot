import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BriefcaseBusiness, ClipboardList, FileText, Play, Upload } from "lucide-react";
import { Link } from "react-router-dom";
import { listApplications } from "../api/applications";
import { listSavedJobs } from "../api/jobs";
import { listPipelineRuns } from "../api/pipeline";
import { listResumes } from "../api/resumes";
import { ErrorBanner, Metric, PageHeader, Section, StatusBadge } from "../components/common/Ui";
import { formatDate } from "../utils/formatting";

export function DashboardPage() {
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: listResumes });
  const jobs = useQuery({ queryKey: ["jobs"], queryFn: () => listSavedJobs("?limit=100") });
  const applications = useQuery({ queryKey: ["applications"], queryFn: () => listApplications("?limit=100") });
  const runs = useQuery({ queryKey: ["pipeline-runs"], queryFn: listPipelineRuns });
  const error = resumes.error || jobs.error || applications.error || runs.error;
  return <div className="page">
    <PageHeader title="Career workspace" description="Move from one master resume to focused applications." action={<Link className="button primary" to="/pipeline"><Play size={17} /> Run pipeline</Link>} />
    {error && <ErrorBanner error={error} />}
    <div className="metrics-grid">
      <Metric label="Master resumes" value={resumes.data?.length ?? "—"} note="Structured and validated" />
      <Metric label="Saved jobs" value={jobs.data?.length ?? "—"} note="Ranked opportunities" />
      <Metric label="Applications" value={applications.data?.length ?? "—"} note="Tracked locally" />
      <Metric label="Pipeline runs" value={runs.data?.length ?? "—"} note="Pollable workflows" />
    </div>
    <div className="dashboard-grid">
      <Section title="Start here"><div className="action-list">
        <Link to="/upload"><Upload size={19} /><span><strong>Upload a resume</strong><small>Parse and validate a PDF or DOCX</small></span><ArrowRight size={17} /></Link>
        <Link to="/pipeline"><Play size={19} /><span><strong>Run job search pipeline</strong><small>Search, analyze, optimize, and export</small></span><ArrowRight size={17} /></Link>
        <Link to="/jobs"><BriefcaseBusiness size={19} /><span><strong>Review saved jobs</strong><small>Compare fit and ATS scores</small></span><ArrowRight size={17} /></Link>
        <Link to="/applications"><ClipboardList size={19} /><span><strong>Track applications</strong><small>Follow status and next steps</small></span><ArrowRight size={17} /></Link>
      </div></Section>
      <Section title="Recent pipeline runs">
        {runs.data?.length ? <div className="compact-list">{runs.data.slice(0, 5).map((run) => <Link key={run.id} to={`/pipeline/runs/${run.id}`}><span><strong>{run.current_step?.replaceAll("_", " ") || "Pipeline run"}</strong><small>{formatDate(run.created_at)}</small></span><StatusBadge status={run.status} /></Link>)}</div> : <p className="muted">No pipeline runs yet.</p>}
      </Section>
    </div>
    <Section title="Workflow"><div className="workflow-strip">{["Resume", "Profile", "Jobs", "Analysis", "Optimization", "Applications"].map((item, index) => <div key={item}><span>{index + 1}</span><strong>{item}</strong></div>)}</div></Section>
  </div>;
}
