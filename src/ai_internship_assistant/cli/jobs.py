"""Saved-job CLI commands."""

from pathlib import Path
from typing import Annotated, cast

import typer

from ai_internship_assistant.cli.common import (
    CliContext,
    CliInputError,
    fail,
    json_echo,
    load_json_model,
    preview,
)
from ai_internship_assistant.domain.models import ATSMatchReport, JobAnalysis, JobPosting
from ai_internship_assistant.storage import (
    DatabaseUnavailableError,
    SavedJobNotFoundError,
)
from ai_internship_assistant.storage.repositories import CorruptedArtifactError

app = typer.Typer(help="Save and inspect job postings.", no_args_is_help=True)
_EXPECTED_ERRORS = (
    CliInputError,
    CorruptedArtifactError,
    DatabaseUnavailableError,
    SavedJobNotFoundError,
)


@app.command("save")
def save_job(
    ctx: typer.Context,
    file: Annotated[Path, typer.Option("--file", help="JobPosting-compatible JSON file.")],
    analysis_file: Annotated[Path | None, typer.Option("--analysis-file")] = None,
    ats_file: Annotated[Path | None, typer.Option("--ats-file")] = None,
    fit_score: Annotated[float | None, typer.Option("--fit-score", min=0.0, max=100.0)] = None,
    note: Annotated[str | None, typer.Option("--note")] = None,
    allow_duplicate: Annotated[bool, typer.Option("--allow-duplicate")] = False,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Save a validated job snapshot from JSON."""

    try:
        job = load_json_model(file, JobPosting)
        analysis = load_json_model(analysis_file, JobAnalysis) if analysis_file else None
        ats_report = load_json_model(ats_file, ATSMatchReport) if ats_file else None
        saved = _context(ctx).tracking.save_job(
            job,
            analysis,
            ats_report,
            fit_score=fit_score,
            notes=note,
            allow_duplicate=allow_duplicate,
        )
    except _EXPECTED_ERRORS as exc:
        fail(str(exc))
    if as_json:
        json_echo(saved)
        return
    typer.echo(f"Saved job {saved.id}: {saved.title} at {saved.company}")


@app.command("list")
def list_jobs(
    ctx: typer.Context,
    company: Annotated[str | None, typer.Option("--company")] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
    active_only: Annotated[bool, typer.Option("--active-only")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 20,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List saved jobs without printing raw snapshots."""

    try:
        jobs = _context(ctx).tracking.list_saved_jobs(
            company=company,
            source=source,
            active_only=active_only,
            limit=limit,
        )
    except _EXPECTED_ERRORS as exc:
        fail(str(exc))
    if as_json:
        json_echo([job.model_dump(mode="json") for job in jobs])
        return
    typer.echo("ID | TITLE | COMPANY | LOCATION | SOURCE | SAVED | ATS")
    for job in jobs:
        ats = f"{job.ats_score:.1f}" if job.ats_score is not None else "-"
        typer.echo(
            f"{job.id} | {job.title} | {job.company} | {job.location or '-'} | "
            f"{job.source} | {job.saved_at.date().isoformat()} | {ats}"
        )


@app.command("show")
def show_job(
    ctx: typer.Context,
    saved_job_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show one saved job."""

    try:
        job = _context(ctx).tracking.get_saved_job(saved_job_id)
    except _EXPECTED_ERRORS as exc:
        message = (
            f"Saved job not found: {saved_job_id}"
            if isinstance(exc, SavedJobNotFoundError)
            else str(exc)
        )
        fail(message)
    if as_json:
        json_echo(job)
        return
    typer.echo(f"{job.title} at {job.company}")
    typer.echo(f"ID: {job.id}")
    typer.echo(f"Location: {job.location or '-'}")
    typer.echo(f"Source: {job.source}")
    typer.echo(f"Apply URL: {job.apply_url or '-'}")
    typer.echo(f"Saved: {job.saved_at.isoformat()}")
    typer.echo(f"ATS score: {job.ats_score if job.ats_score is not None else '-'}")
    typer.echo(f"Fit score: {job.fit_score if job.fit_score is not None else '-'}")
    typer.echo(f"Description: {preview(job.job_posting.description, 200)}")
    typer.echo(f"Notes: {job.notes or '-'}")


@app.command("archive")
def archive_job(ctx: typer.Context, saved_job_id: str) -> None:
    """Archive a saved job without deleting application records."""

    try:
        job = _context(ctx).tracking.archive_saved_job(saved_job_id)
    except _EXPECTED_ERRORS as exc:
        message = (
            f"Saved job not found: {saved_job_id}"
            if isinstance(exc, SavedJobNotFoundError)
            else str(exc)
        )
        fail(message)
    typer.echo(f"Archived saved job {job.id}.")


def _context(ctx: typer.Context) -> CliContext:
    return cast(CliContext, ctx.find_root().obj)
