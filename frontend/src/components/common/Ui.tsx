import type { ReactNode } from "react";
import { AlertCircle, Inbox, LoaderCircle } from "lucide-react";

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <header className="page-header"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</header>;
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return <div className="state-line" role="status"><LoaderCircle className="spin" size={18} />{label}</div>;
}

export function ErrorBanner({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return <div className="error-banner" role="alert"><AlertCircle size={18} /><span>{message}</span></div>;
}

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return <div className="empty-state"><Inbox size={28} /><h3>{title}</h3><p>{body}</p>{action}</div>;
}

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status status-${status}`}>{status.replaceAll("_", " ")}</span>;
}

export function Metric({ label, value, note }: { label: string; value: ReactNode; note?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return <section className="section"><div className="section-heading"><h2>{title}</h2>{action}</div>{children}</section>;
}

export function ChipList({ items }: { items: string[] }) {
  return <div className="chips">{items.map((item) => <span className="chip" key={item}>{item}</span>)}</div>;
}
