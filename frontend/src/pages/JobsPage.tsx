import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Search, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { analyzeSavedJob, getSavedJob, listSavedJobs } from "../api/jobs";
import { ChipList, EmptyState, ErrorBanner, Loading, Metric, PageHeader, Section } from "../components/common/Ui";
import { formatDate, score } from "../utils/formatting";

export function JobsPage() {
  const [search, setSearch] = useState("");
  const [company, setCompany] = useState("");
  const [source, setSource] = useState("");
  const [activeOnly, setActiveOnly] = useState(false);
  const params = new URLSearchParams();
  if (company) params.set("company", company);
  if (source) params.set("source", source);
  if (activeOnly) params.set("active_only", "true");
  params.set("limit", "100");
  const jobs = useQuery({ queryKey: ["jobs", company, source, activeOnly], queryFn: () => listSavedJobs(`?${params}`) });
  const filtered = jobs.data?.filter((job) => `${job.title} ${job.company}`.toLowerCase().includes(search.toLowerCase()));
  return <div className="page"><PageHeader title="Saved jobs" description="Review ranked opportunities and job-analysis artifacts." />
    <div className="filter-bar"><label className="search-field"><Search size={16} /><input aria-label="Search jobs" placeholder="Search title or company" value={search} onChange={(event) => setSearch(event.target.value)} /></label><input aria-label="Filter company" placeholder="Company" value={company} onChange={(event) => setCompany(event.target.value)} /><input aria-label="Filter source" placeholder="Source" value={source} onChange={(event) => setSource(event.target.value)} /><label className="toggle-row"><input type="checkbox" checked={activeOnly} onChange={(event) => setActiveOnly(event.target.checked)} /> Active only</label></div>
    {jobs.isLoading ? <Loading /> : jobs.error ? <ErrorBanner error={jobs.error} /> : filtered?.length ? <div className="job-table"><div className="job-table-head"><span>Role</span><span>Source</span><span>Fit</span><span>ATS</span><span>Saved</span></div>{filtered.map((job) => <Link key={job.id} to={`/jobs/${job.id}`}><span><strong>{job.title}</strong><small>{job.company} · {job.location || "Location not listed"}</small></span><span>{job.source}</span><span>{score(job.fit_score)}</span><span>{score(job.ats_score)}</span><span>{formatDate(job.saved_at)}</span></Link>)}</div> : <EmptyState title="No saved jobs yet" body="Run the pipeline to discover and save ranked roles." action={<Link className="button primary" to="/pipeline">Run pipeline</Link>} />}
  </div>;
}

export function JobDetailPage() {
  const { savedJobId = "" } = useParams();
  const queryClient = useQueryClient();
  const job = useQuery({ queryKey: ["job", savedJobId], queryFn: () => getSavedJob(savedJobId) });
  const analyze = useMutation({ mutationFn: () => analyzeSavedJob(savedJobId), onSuccess: () => queryClient.invalidateQueries({ queryKey: ["job", savedJobId] }) });
  if (job.isLoading) return <div className="page"><Loading /></div>;
  if (job.error || !job.data) return <div className="page"><ErrorBanner error={job.error} /></div>;
  return <div className="page"><PageHeader title={job.data.title} description={`${job.data.company} · ${job.data.location || "Location not listed"}`} action={<div className="button-row">{job.data.apply_url && <a className="button primary" href={job.data.apply_url} target="_blank" rel="noreferrer">Apply <ExternalLink size={16} /></a>}<button className="button secondary" onClick={() => analyze.mutate()}><Sparkles size={16} /> Analyze</button></div>} />
    {analyze.error && <ErrorBanner error={analyze.error} />}
    <div className="metrics-grid"><Metric label="Fit score" value={score(job.data.fit_score)} /><Metric label="ATS score" value={score(job.data.ats_score)} /><Metric label="Source" value={job.data.source} /><Metric label="Saved" value={formatDate(job.data.saved_at)} /></div>
    <Section title="Description"><p className="summary-text">{job.data.job.description || "No job description stored."}</p></Section>
    <div className="split-grid"><Section title="Technologies"><ChipList items={job.data.job.technologies} /></Section><Section title="Requirements"><ul>{job.data.job.requirements.map((item) => <li key={item}>{item}</li>)}</ul></Section></div>
    <Section title="Analysis">{job.data.job_analysis ? <pre className="developer-json">{JSON.stringify(job.data.job_analysis, null, 2)}</pre> : <p className="muted">No analysis yet. Run analysis to extract structured requirements.</p>}</Section>
  </div>;
}
