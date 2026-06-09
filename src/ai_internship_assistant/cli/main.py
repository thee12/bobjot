"""Top-level jobbot CLI entrypoint."""

from typing import Annotated

import typer

from ai_internship_assistant.cli import applications, jobs
from ai_internship_assistant.cli.common import build_context, fail, resolve_database_url
from ai_internship_assistant.storage import DatabaseUnavailableError

app = typer.Typer(
    name="jobbot",
    help="Developer-facing application tracker.",
    no_args_is_help=True,
)
app.add_typer(jobs.app, name="jobs")
app.add_typer(applications.app, name="applications")


@app.callback()
def callback(
    ctx: typer.Context,
    db_url: Annotated[
        str | None,
        typer.Option(
            "--db-url",
            envvar="JOBBOT_DATABASE_URL",
            help="Database URL; defaults to JOBBOT_DATABASE_URL or application settings.",
        ),
    ] = None,
) -> None:
    """Initialize the configured application-tracking database."""

    try:
        ctx.obj = build_context(resolve_database_url(db_url))
    except (DatabaseUnavailableError, OSError) as exc:
        fail(str(exc))


def main() -> None:
    """Run the jobbot command-line application."""

    app()
