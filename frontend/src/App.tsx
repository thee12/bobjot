import { Route, Routes } from "react-router-dom";
import { AppLayout } from "./components/layout/AppLayout";
import { ApplicationDetailPage, ApplicationsPage } from "./pages/ApplicationsPage";
import { DashboardPage } from "./pages/DashboardPage";
import { JobDetailPage, JobsPage } from "./pages/JobsPage";
import { PipelinePage, PipelineRunPage } from "./pages/PipelinePage";
import { ResumeDetailPage, ResumesPage, ResumeVersionPage } from "./pages/ResumesPage";
import { ResumeUploadPage } from "./pages/ResumeUploadPage";

export function App() {
  return <Routes><Route element={<AppLayout />}>
    <Route path="/" element={<DashboardPage />} />
    <Route path="/upload" element={<ResumeUploadPage />} />
    <Route path="/resumes" element={<ResumesPage />} />
    <Route path="/resumes/:resumeId" element={<ResumeDetailPage />} />
    <Route path="/pipeline" element={<PipelinePage />} />
    <Route path="/pipeline/runs/:pipelineRunId" element={<PipelineRunPage />} />
    <Route path="/jobs" element={<JobsPage />} />
    <Route path="/jobs/:savedJobId" element={<JobDetailPage />} />
    <Route path="/resume-versions/:versionId" element={<ResumeVersionPage />} />
    <Route path="/applications" element={<ApplicationsPage />} />
    <Route path="/applications/:applicationId" element={<ApplicationDetailPage />} />
  </Route></Routes>;
}
