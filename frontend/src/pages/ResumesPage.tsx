import { useMutation, useQuery } from "@tanstack/react-query";
import { Download, FileText, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { exportResumeVersion, getExportDownloadUrl } from "../api/exports";
import { getResume, getResumeVersion, listResumes, listResumeVersions } from "../api/resumes";
import { ChipList, EmptyState, ErrorBanner, Loading, Metric, PageHeader, Section, StatusBadge } from "../components/common/Ui";
import { formatDate, score, titleCase } from "../utils/formatting";

export function ResumesPage() {
  const resumes = useQuery({ queryKey: ["resumes"], queryFn: listResumes });
  return <div className="page"><PageHeader title="Resumes" description="Master resumes and their optimized versions." />
    {resumes.isLoading ? <Loading /> : resumes.error ? <ErrorBanner error={resumes.error} /> : resumes.data?.length ? <div className="data-list">{resumes.data.map((resume) => <Link className="data-row" key={resume.resume_id} to={`/resumes/${resume.resume_id}`}><FileText size={20} /><span className="grow"><strong>{resume.candidate_name || "Unnamed candidate"}</strong><small>{resume.original_filename || "Structured resume"} · Updated {formatDate(resume.updated_at)}</small></span><span className="count">{resume.version_count} versions</span></Link>)}</div> : <EmptyState title="No resumes uploaded yet" body="Upload a PDF or DOCX to begin." action={<Link className="button primary" to="/upload">Upload resume</Link>} />}
  </div>;
}

export function ResumeDetailPage() {
  const { resumeId = "" } = useParams();
  const detail = useQuery({ queryKey: ["resume", resumeId], queryFn: () => getResume(resumeId) });
  const versions = useQuery({ queryKey: ["resume-versions", resumeId], queryFn: () => listResumeVersions(resumeId) });
  if (detail.isLoading) return <div className="page"><Loading /></div>;
  if (detail.error || !detail.data) return <div className="page"><ErrorBanner error={detail.error} /></div>;
  const { parsed_resume: resume, candidate_profile: profile, validation_report: validation } = detail.data;
  return <div className="page">
    <PageHeader title={detail.data.candidate_name || "Resume detail"} description={`${titleCase(profile.experience_level)} · ${profile.primary_domain}`} action={<Link className="button primary" to={`/pipeline?resume=${resumeId}`}>Run pipeline</Link>} />
    <div className="metrics-grid"><Metric label="Profile confidence" value={score(profile.confidence_score * 100)} /><Metric label="Core skills" value={profile.core_skills.length} /><Metric label="Validation warnings" value={validation.warning_count} /><Metric label="Optimized versions" value={versions.data?.length ?? "—"} /></div>
    <Section title="Profile summary"><p className="summary-text">{profile.profile_summary}</p><ChipList items={profile.target_roles} /></Section>
    <div className="split-grid"><Section title="Contact"><dl className="detail-list"><dt>Email</dt><dd>{resume.email || "Not provided"}</dd><dt>Phone</dt><dd>{resume.phone || "Not provided"}</dd><dt>Location</dt><dd>{resume.location || "Not provided"}</dd><dt>LinkedIn</dt><dd>{resume.linkedin_url || "Not provided"}</dd></dl></Section><Section title="Skills"><ChipList items={resume.skills.map((item) => item.name)} /></Section></div>
    <Section title="Experience">{resume.experience.length ? <div className="timeline-list">{resume.experience.map((item) => <article key={`${item.organization}-${item.title}`}><h3>{item.title}</h3><p>{item.organization} · {[item.start_date, item.end_date].filter(Boolean).join(" – ")}</p><ul>{item.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul><ChipList items={item.technologies} /></article>)}</div> : <p className="muted">No experience entries parsed.</p>}</Section>
    <div className="split-grid"><Section title="Projects">{resume.projects.length ? resume.projects.map((project) => <article className="item-block" key={project.name}><h3>{project.name}</h3><p>{project.description}</p><ChipList items={project.technologies} /></article>) : <p className="muted">No projects parsed.</p>}</Section><Section title="Education and credentials">{resume.education.map((item) => <article className="item-block" key={item.institution}><h3>{item.institution}</h3><p>{item.degree || item.program} {item.end_date && `· ${item.end_date}`}</p></article>)}{resume.certifications.map((item) => <article className="item-block" key={item.name}><h3>{item.name}</h3><p>{item.issuer}</p></article>)}</Section></div>
    <Section title="Validation">{validation.issues.length ? <div className="issue-list">{validation.issues.map((issue) => <div key={`${issue.category}-${issue.message}`}><StatusBadge status={issue.severity} /><span><strong>{titleCase(issue.category)}</strong><p>{issue.message}</p></span></div>)}</div> : <p className="muted">No validation issues detected.</p>}</Section>
    <Section title="Optimized versions">{versions.data?.length ? <VersionList versions={versions.data} /> : <p className="muted">No optimized versions yet.</p>}</Section>
  </div>;
}

function VersionList({ versions }: { versions: Awaited<ReturnType<typeof listResumeVersions>> }) {
  return <div className="data-list">{versions.map((version) => <Link className="data-row" key={version.id} to={`/resume-versions/${version.id}`}><FileText size={19} /><span className="grow"><strong>{version.target_job_title || version.version_name}</strong><small>{version.target_company || "General version"} · {formatDate(version.created_at)}</small></span><span className="score-shift">{score(version.before_ats_score)} → {score(version.estimated_after_score_high)}</span></Link>)}</div>;
}

export function ResumeVersionPage() {
  const { versionId = "" } = useParams();
  const version = useQuery({ queryKey: ["resume-version", versionId], queryFn: () => getResumeVersion(versionId) });
  const exportFiles = useMutation({ mutationFn: (formats: string[]) => exportResumeVersion(versionId, formats) });
  if (version.isLoading) return <div className="page"><Loading /></div>;
  if (version.error || !version.data) return <div className="page"><ErrorBanner error={version.error} /></div>;
  const item = version.data;
  return <div className="page"><PageHeader title={item.target_job_title || "Optimized resume"} description={item.target_company || "Stored optimized version"} action={<button className="button primary" onClick={() => exportFiles.mutate(["docx", "pdf"])}><Download size={17} /> Export DOCX + PDF</button>} />
    {exportFiles.error && <ErrorBanner error={exportFiles.error} />}
    <div className="metrics-grid"><Metric label="Before ATS" value={score(item.before_ats_score)} /><Metric label="Estimated low" value={score(item.estimated_after_score_low)} /><Metric label="Estimated high" value={score(item.estimated_after_score_high)} /><Metric label="Safety" value={<span className="inline-status"><ShieldCheck size={18} />{item.safety_report.passed ? "Passed" : "Review"}</span>} /></div>
    {exportFiles.data && <Section title="Downloads"><div className="button-row">{exportFiles.data.exported_files.map((file) => <a className="button secondary" key={file.file_id} href={getExportDownloadUrl(file.file_id)}><Download size={16} /> {file.filename}</a>)}</div></Section>}
    <Section title="Change log">{item.change_log.length ? <div className="timeline-list">{item.change_log.map((change, index) => <article key={index}><h3>{titleCase(change.change_type || change.section)}</h3><p>{change.explanation || "Safe, evidence-backed adjustment."}</p></article>)}</div> : <p className="muted">No changes recorded.</p>}</Section>
  </div>;
}
