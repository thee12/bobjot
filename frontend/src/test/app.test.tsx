import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";

const jsonResponse = (data: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }));

const renderApp = (route = "/") => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[route]}><App /></MemoryRouter></QueryClientProvider>);
};

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(() => jsonResponse([])));
});

afterEach(() => vi.unstubAllGlobals());

describe("frontend foundation", () => {
  it("renders the app and navigation", async () => {
    renderApp();
    expect(screen.getByText("Career workspace")).toBeInTheDocument();
    expect(screen.getByText("Upload Resume")).toBeInTheDocument();
    expect(screen.getAllByText("Applications").length).toBeGreaterThan(0);
  });

  it("rejects an unsupported resume file", async () => {
    renderApp("/upload");
    const input = screen.getByLabelText("Resume file");
    fireEvent.change(input, {
      target: { files: [new File(["bad"], "resume.exe", { type: "application/octet-stream" })] },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a PDF or DOCX resume.");
  });

  it("shows successful resume upload data", async () => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({
      resume_id: "resume-1", candidate_name: "Alex Candidate", validation_warnings: [],
      candidate_profile_summary: "Entry-level security candidate.", created_at: "2026-06-09T12:00:00Z",
    }, 201)));
    renderApp("/upload");
    await userEvent.upload(screen.getByLabelText("Resume file"), new File(["%PDF"], "resume.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload and parse" }));
    expect(await screen.findByText("Alex Candidate")).toBeInTheDocument();
  });

  it("shows upload API errors", async () => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse({ detail: "Resume upload failed." }, 503)));
    renderApp("/upload");
    await userEvent.upload(screen.getByLabelText("Resume file"), new File(["%PDF"], "resume.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Upload and parse" }));
    expect(await screen.findByText("Resume upload failed.")).toBeInTheDocument();
  });

  it("renders and validates the pipeline form", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.endsWith("/resumes")) return jsonResponse([{ resume_id: "resume-1", candidate_name: "Alex", version_count: 0 }]);
      return jsonResponse([]);
    }));
    renderApp("/pipeline?resume=resume-1");
    expect(await screen.findByText("New pipeline run")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Jobs to analyze"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Jobs to optimize"), { target: { value: "3" } });
    await userEvent.click(screen.getByRole("button", { name: "Start background run" }));
    expect(screen.getByRole("alert")).toHaveTextContent("cannot exceed");
  });

  it("renders saved jobs and applications", async () => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = input.toString();
      if (url.includes("/jobs/saved")) return jsonResponse([{ id: "j1", title: "SOC Analyst Intern", company: "Example Security", source: "mock", saved_at: "2026-06-09", fit_score: 88, ats_score: 72, is_active: true, job: { technologies: [], requirements: [], preferred_qualifications: [] } }]);
      return jsonResponse([]);
    }));
    renderApp("/jobs");
    expect(await screen.findByText("SOC Analyst Intern")).toBeInTheDocument();
    expect(screen.getByText(/Example Security/)).toBeInTheDocument();
  });

  it("polls a running pipeline and stops once complete", async () => {
    let calls = 0;
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      calls += 1;
      const url = input.toString();
      if (url.endsWith("/steps")) return jsonResponse([]);
      if (url.endsWith("/result")) return jsonResponse({ resume_id: "r", jobs_found: 0, saved_job_ids: [], analyzed_job_ids: [], resume_version_ids: [], export_file_ids: [], application_ids: [], warnings: [], errors: [] });
      return jsonResponse({ id: "p1", resume_id: "r", status: "completed", current_step: "finalize", progress_percentage: 100, warning_count: 0, error_count: 0, created_at: "2026-06-09", execution_mode: "local_background", cancellation_requested: false });
    }));
    renderApp("/pipeline/runs/p1");
    expect(await screen.findByText("100%")).toBeInTheDocument();
    await waitFor(() => expect(calls).toBeLessThan(6));
  });
});
