import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, MessageSquarePlus } from "lucide-react";
import { FormEvent, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { addApplicationNote, getApplication, listApplications, setFollowUp, updateApplicationStatus } from "../api/applications";
import { EmptyState, ErrorBanner, Loading, PageHeader, Section, StatusBadge } from "../components/common/Ui";
import { formatDate, formatDateTime, titleCase } from "../utils/formatting";

export function ApplicationsPage() {
  const [company, setCompany] = useState("");
  const [status, setStatus] = useState("");
  const [followUp, setFollowUpOnly] = useState(false);
  const params = new URLSearchParams();
  if (company) params.set("company", company);
  if (status) params.set("status", status);
  if (followUp) params.set("needs_follow_up", "true");
  const applications = useQuery({ queryKey: ["applications", company, status, followUp], queryFn: () => listApplications(`?${params}`) });
  return <div className="page"><PageHeader title="Applications" description="Track status, follow-ups, and the resume version used." />
    <div className="filter-bar"><input aria-label="Filter application company" placeholder="Company" value={company} onChange={(event) => setCompany(event.target.value)} /><select aria-label="Filter application status" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">All statuses</option>{["planned", "ready_to_apply", "applied", "follow_up_needed", "interviewing", "technical_interview", "final_interview", "offer", "rejected", "withdrawn", "closed"].map((value) => <option key={value} value={value}>{titleCase(value)}</option>)}</select><label className="toggle-row"><input type="checkbox" checked={followUp} onChange={(event) => setFollowUpOnly(event.target.checked)} /> Needs follow-up</label></div>
    {applications.isLoading ? <Loading /> : applications.error ? <ErrorBanner error={applications.error} /> : applications.data?.length ? <div className="application-board">{applications.data.map((item) => <Link key={item.id} to={`/applications/${item.id}`}><div><strong>{item.title}</strong><span>{item.company}</span></div><StatusBadge status={item.status} /><dl><dt>Applied</dt><dd>{formatDate(item.applied_at)}</dd><dt>Follow-up</dt><dd>{formatDate(item.follow_up_date)}</dd></dl></Link>)}</div> : <EmptyState title="No applications tracked" body="Create planned applications from a pipeline run." action={<Link className="button primary" to="/pipeline">Run pipeline</Link>} />}
  </div>;
}

export function ApplicationDetailPage() {
  const { applicationId = "" } = useParams();
  const queryClient = useQueryClient();
  const detail = useQuery({ queryKey: ["application", applicationId], queryFn: () => getApplication(applicationId) });
  const [status, setStatus] = useState("applied");
  const [note, setNote] = useState("");
  const [followUp, setFollowUpDate] = useState("");
  const refresh = () => { queryClient.invalidateQueries({ queryKey: ["application", applicationId] }); queryClient.invalidateQueries({ queryKey: ["applications"] }); };
  const updateStatus = useMutation({ mutationFn: () => updateApplicationStatus(applicationId, status), onSuccess: refresh });
  const addNote = useMutation({ mutationFn: () => addApplicationNote(applicationId, note), onSuccess: () => { setNote(""); refresh(); } });
  const updateFollowUp = useMutation({ mutationFn: () => setFollowUp(applicationId, followUp || null), onSuccess: refresh });
  if (detail.isLoading) return <div className="page"><Loading /></div>;
  if (detail.error || !detail.data) return <div className="page"><ErrorBanner error={detail.error} /></div>;
  const item = detail.data;
  return <div className="page"><PageHeader title={item.saved_job.title} description={`${item.saved_job.company} · ${item.saved_job.location || "Location not listed"}`} action={<StatusBadge status={item.application.status} />} />
    <div className="split-grid"><Section title="Update status"><form className="inline-form" onSubmit={(event) => { event.preventDefault(); updateStatus.mutate(); }}><select value={status} onChange={(event) => setStatus(event.target.value)}>{["planned", "ready_to_apply", "applied", "follow_up_needed", "interviewing", "technical_interview", "final_interview", "offer", "rejected", "withdrawn", "closed"].map((value) => <option key={value}>{value}</option>)}</select><button className="button primary">Update</button></form></Section><Section title="Follow-up"><form className="inline-form" onSubmit={(event) => { event.preventDefault(); updateFollowUp.mutate(); }}><input aria-label="Follow-up date" type="date" value={followUp} onChange={(event) => setFollowUpDate(event.target.value)} /><button className="button secondary"><CalendarClock size={16} /> Set date</button></form></Section></div>
    <Section title="Add note"><form className="inline-form wide" onSubmit={(event: FormEvent) => { event.preventDefault(); if (note.trim()) addNote.mutate(); }}><input aria-label="Application note" placeholder="Add a private application note" value={note} onChange={(event) => setNote(event.target.value)} /><button className="button secondary"><MessageSquarePlus size={16} /> Add note</button></form></Section>
    <div className="split-grid"><Section title="Notes">{item.notes.length ? <div className="timeline-list">{item.notes.map((entry) => <article key={entry.id}><h3>{titleCase(entry.note_type)}</h3><p>{entry.note}</p><small>{formatDateTime(entry.created_at)}</small></article>)}</div> : <p className="muted">No notes yet.</p>}</Section><Section title="Status history"><div className="timeline-list">{item.status_history.map((entry) => <article key={entry.id}><h3>{titleCase(entry.new_status)}</h3><p>{entry.note || "Status updated."}</p><small>{formatDateTime(entry.changed_at)}</small></article>)}</div></Section></div>
  </div>;
}
