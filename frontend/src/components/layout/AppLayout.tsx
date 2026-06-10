import { BriefcaseBusiness, ClipboardList, FileText, Gauge, Menu, Play, Upload, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";

const navigation = [
  { to: "/", label: "Dashboard", icon: Gauge },
  { to: "/upload", label: "Upload Resume", icon: Upload },
  { to: "/pipeline", label: "Pipeline", icon: Play },
  { to: "/jobs", label: "Jobs", icon: BriefcaseBusiness },
  { to: "/resumes", label: "Resume Versions", icon: FileText },
  { to: "/applications", label: "Applications", icon: ClipboardList },
];

export function AppLayout() {
  const [open, setOpen] = useState(false);
  return <div className="app-shell">
    <aside className={open ? "sidebar sidebar-open" : "sidebar"}>
      <div className="brand"><div className="brand-mark">CO</div><div><strong>CareerOps</strong><span>Application assistant</span></div></div>
      <button className="icon-button mobile-close" aria-label="Close navigation" onClick={() => setOpen(false)}><X size={20} /></button>
      <nav>{navigation.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} end={to === "/"} onClick={() => setOpen(false)}><Icon size={18} />{label}</NavLink>)}</nav>
      <div className="local-notice"><span>Local workspace</span><p>Authentication is not enabled.</p></div>
    </aside>
    <div className="main-column">
      <header className="topbar"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setOpen(true)}><Menu size={20} /></button><span className="connection"><i /> Backend workspace</span></header>
      <main><Outlet /></main>
    </div>
  </div>;
}
