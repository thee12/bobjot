"""Job-application CLI commands."""

from collections.abc import Sequence
from datetime import date
from typing import Annotated, cast

import typer

from ai_internship_assistant.cli.common import (
    CliContext,
    CliInputError,
    fail,
    json_echo,
    parse_enum,
    preview,
)
from ai_internship_assistant.domain.models import (
    ApplicationFilters,
    ApplicationNoteType,
    ApplicationStatus,
    JobApplicationSummary,
)
from ai_internship_assistant.services import ApplicationTrackingError
from ai_internship_assistant.storage import (
    ApplicationNotFoundError,
    DatabaseUnavailableError,
    ResumeVersionNotFoundError,
    SavedJobNotFoundError,
)
from ai_internship_assistant.storage.repositories import CorruptedArtifactError

app = typer.Typer(help="Create and manage job applications.", no_args_is_help=True)
_EXPECTED_ERRORS = (
    ApplicationNotFoundError,
    ApplicationTrackingError,
    CliInputError,
    CorruptedArtifactError,
    DatabaseUnavailableError,
    ResumeVersionNotFoundError,
    SavedJobNotFoundError,
)


@app.command("create")
def create_application(
    ctx: typer.Context,
    job: Annotated[str, typer.Option("--job", help="Saved job ID.")],
    resume_version: Annotated[str | None, typer.Option("--resume-version")] = None,
    status: Annotated[str, typer.Option("--status")] = "PLANNED",
    note: Annotated[str | None, typer.Option("--note")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Create an application from a saved job."""

    try:
        parsed_status = parse_enum(status, ApplicationStatus, "application status")
        application = _context(ctx).tracking.create_application(
            job,
            resume_version,
            parsed_status,
            notes=note,
        )
    except _EXPECTED_ERRORS as exc:
        fail(str(exc))
    if as_json:
        json_echo(application)
        return
    typer.echo(
        f"Created application {application.id} with status {application.status.value.upper()}."
    )


@app.command("list")
def list_applications(
    ctx: typer.Context,
    status: Annotated[str | None, typer.Option("--status")] = None,
    company: Annotated[str | None, typer.Option("--company")] = None,
    role: Annotated[str | None, typer.Option("--role")] = None,
    source: Annotated[str | None, typer.Option("--source")] = None,
    needs_follow_up: Annotated[bool, typer.Option("--needs-follow-up")] = False,
    has_interview: Annotated[bool, typer.Option("--has-interview")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 50,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List application summaries with optional filters."""

    try:
        filters = ApplicationFilters(
            status=parse_enum(status, ApplicationStatus, "application status") if status else None,
            company=company,
            role_keyword=role,
            source=source,
            needs_follow_up=True if needs_follow_up else None,
            has_interview=True if has_interview else None,
        )
        applications = _context(ctx).tracking.list_applications(filters, limit=limit)
    except _EXPECTED_ERRORS as exc:
        fail(str(exc))
    if as_json:
        json_echo([item.model_dump(mode="json") for item in applications])
        return
    _echo_summaries(applications)


@app.command("show")
def show_application(
    ctx: typer.Context,
    application_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show an application, saved job, notes, and status history."""

    try:
        service = _context(ctx).tracking
        application = service.get_application(application_id)
        summary = service.get_application_summary(application_id)
        saved_job = service.get_saved_job(application.saved_job_id)
        notes = service.list_application_notes(application_id)
        history = service.get_application_history(application_id)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    if as_json:
        json_echo(
            {
                "application": application.model_dump(mode="json"),
                "saved_job": saved_job.model_dump(mode="json"),
                "notes": [note.model_dump(mode="json") for note in notes],
                "status_history": [item.model_dump(mode="json") for item in history],
            }
        )
        return
    typer.echo(f"{summary.title} at {summary.company}")
    typer.echo(f"Application ID: {application.id}")
    typer.echo(f"Apply URL: {saved_job.apply_url or '-'}")
    typer.echo(f"Status: {application.status.value.upper()}")
    typer.echo(f"Resume version: {application.resume_version_id or '-'}")
    typer.echo(f"Applied: {application.applied_at.isoformat() if application.applied_at else '-'}")
    typer.echo(f"Follow-up: {application.follow_up_date or '-'}")
    interview = application.interview_date.isoformat() if application.interview_date else "-"
    typer.echo(f"Interview: {interview}")
    typer.echo("Notes:")
    for note in notes:
        typer.echo(f"  {note.created_at.isoformat()} [{note.note_type.value}] {note.note}")
    typer.echo("Status history:")
    for item in history:
        typer.echo(
            _history_line(item.changed_at.isoformat(), item.old_status, item.new_status, item.note)
        )


@app.command("status")
def update_status(
    ctx: typer.Context,
    application_id: str,
    new_status: str,
    note: Annotated[str | None, typer.Option("--note")] = None,
) -> None:
    """Update status and append its audit record."""

    try:
        service = _context(ctx).tracking
        old = service.get_application(application_id).status
        parsed_status = parse_enum(new_status, ApplicationStatus, "application status")
        updated = service.update_application_status(application_id, parsed_status, note)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    typer.echo(f"Updated {application_id}: {old.value.upper()} -> {updated.status.value.upper()}")


@app.command("note")
def add_note(
    ctx: typer.Context,
    application_id: str,
    note: str,
    note_type: Annotated[str, typer.Option("--type")] = "GENERAL",
) -> None:
    """Append a typed application note."""

    try:
        parsed_type = parse_enum(note_type, ApplicationNoteType, "note type")
        created = _context(ctx).tracking.add_application_note(application_id, note, parsed_type)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    typer.echo(f"Added note {created.id} at {created.created_at.isoformat()}.")


@app.command("followup")
def set_follow_up(ctx: typer.Context, application_id: str, follow_up_date: str) -> None:
    """Set an ISO-formatted follow-up date without creating a reminder."""

    try:
        parsed_date = date.fromisoformat(follow_up_date)
    except ValueError:
        fail(f"Invalid date: {follow_up_date}. Use YYYY-MM-DD.")
    try:
        updated = _context(ctx).tracking.set_follow_up_date(application_id, parsed_date)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    typer.echo(f"Follow-up for {application_id} set to {updated.follow_up_date}.")


@app.command("due")
def due_follow_ups(
    ctx: typer.Context,
    as_of: Annotated[str | None, typer.Option("--as-of")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """List applications with due follow-up dates."""

    try:
        parsed_date = date.fromisoformat(as_of) if as_of else None
    except ValueError:
        fail(f"Invalid date: {as_of}. Use YYYY-MM-DD.")
    try:
        applications = _context(ctx).tracking.list_follow_ups_due(as_of_date=parsed_date)
    except _EXPECTED_ERRORS as exc:
        fail(str(exc))
    if as_json:
        json_echo([item.model_dump(mode="json") for item in applications])
        return
    _echo_summaries(applications)


@app.command("history")
def show_history(
    ctx: typer.Context,
    application_id: str,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show chronological application status history."""

    try:
        history = _context(ctx).tracking.get_application_history(application_id)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    if as_json:
        json_echo([item.model_dump(mode="json") for item in history])
        return
    for item in history:
        typer.echo(
            _history_line(item.changed_at.isoformat(), item.old_status, item.new_status, item.note)
        )


@app.command("link-resume")
def link_resume(ctx: typer.Context, application_id: str, resume_version_id: str) -> None:
    """Link an existing optimized resume version to an application."""

    try:
        updated = _context(ctx).tracking.link_resume_version(application_id, resume_version_id)
    except _EXPECTED_ERRORS as exc:
        fail(_application_error(exc, application_id))
    typer.echo(
        f"Linked application {application_id} to resume version {updated.resume_version_id}."
    )


def _echo_summaries(applications: Sequence[JobApplicationSummary]) -> None:
    typer.echo("ID | TITLE | COMPANY | STATUS | APPLIED | FOLLOW-UP | RESUME | LATEST NOTE")
    for item in applications:
        typer.echo(
            f"{item.id} | {item.title} | {item.company} | {item.status.value.upper()} | "
            f"{item.applied_at.date().isoformat() if item.applied_at else '-'} | "
            f"{item.follow_up_date or '-'} | {item.resume_version_id or '-'} | "
            f"{preview(item.latest_note)}"
        )


def _history_line(
    changed_at: str,
    old_status: ApplicationStatus | None,
    new_status: ApplicationStatus,
    note: str | None,
) -> str:
    old = old_status.value.upper() if old_status else "-"
    return f"{changed_at} | {old} -> {new_status.value.upper()} | {preview(note)}"


def _application_error(exc: Exception, application_id: str) -> str:
    if isinstance(exc, ApplicationNotFoundError):
        return f"Application not found: {application_id}"
    return str(exc)


def _context(ctx: typer.Context) -> CliContext:
    return cast(CliContext, ctx.find_root().obj)
