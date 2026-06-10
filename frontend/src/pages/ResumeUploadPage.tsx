import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileUp, Play } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { uploadResume } from "../api/resumes";
import { ErrorBanner, PageHeader, Section } from "../components/common/Ui";

export function ResumeUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [validationError, setValidationError] = useState("");
  const queryClient = useQueryClient();
  const upload = useMutation({
    mutationFn: uploadResume,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["resumes"] }),
  });
  const chooseFile = (selected?: File) => {
    if (!selected) return;
    const valid = selected.name.toLowerCase().endsWith(".pdf") || selected.name.toLowerCase().endsWith(".docx");
    setValidationError(valid ? "" : "Choose a PDF or DOCX resume.");
    setFile(valid ? selected : null);
  };
  return <div className="page narrow">
    <PageHeader title="Upload master resume" description="The backend extracts, parses, validates, and stores one factual source resume." />
    <Section title="Resume file">
      <form className="upload-form" onSubmit={(event) => { event.preventDefault(); if (file) upload.mutate(file); }}>
        <label className="file-picker"><FileUp size={30} /><strong>{file?.name || "Choose PDF or DOCX"}</strong><span>Maximum file size: 10 MB</span><input aria-label="Resume file" type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={(event) => chooseFile(event.target.files?.[0])} /></label>
        {validationError && <div className="field-error" role="alert">{validationError}</div>}
        {upload.error && <ErrorBanner error={upload.error} />}
        <button className="button primary" disabled={!file || upload.isPending} type="submit">{upload.isPending ? "Uploading..." : "Upload and parse"}</button>
      </form>
    </Section>
    {upload.data && <Section title="Resume ready"><div className="success-panel"><CheckCircle2 size={24} /><div><h3>{upload.data.candidate_name || "Parsed resume"}</h3><p>{upload.data.candidate_profile_summary}</p></div></div>{upload.data.validation_warnings.length > 0 && <div className="warning-list"><strong>Validation notes</strong>{upload.data.validation_warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}<div className="button-row"><Link className="button primary" to={`/pipeline?resume=${upload.data.resume_id}`}><Play size={17} /> Run pipeline</Link><Link className="button secondary" to={`/resumes/${upload.data.resume_id}`}>View resume</Link></div></Section>}
  </div>;
}
