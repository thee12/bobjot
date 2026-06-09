"""End-to-end Typer CLI tests using isolated SQLite databases."""

import json
from pathlib import Path

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner, Result

from ai_internship_assistant.cli.main import app
from ai_internship_assistant.services import FullResumeOptimizer, ResumeVersioningService
from ai_internship_assistant.storage import (
    Database,
    JobRepository,
    MasterResumeRepository,
    ResumeVersionRepository,
)
from tests.test_application_tracking import _job
from tests.test_full_resume_optimizer import MockBulletRewriter, _request, _safe_packet_rewrite


@pytest.fixture
def cli(tmp_path: Path) -> tuple[CliRunner, dict[str, str], Path]:
    """Return a runner and environment pointing at one isolated SQLite file."""

    database_path = tmp_path / "tracker.db"
    environment = {"JOBBOT_DATABASE_URL": f"sqlite:///{database_path.as_posix()}"}
    return CliRunner(), environment, database_path


def _invoke(
    cli: tuple[CliRunner, dict[str, str], Path],
    arguments: list[str],
) -> Result:
    runner, environment, _ = cli
    return runner.invoke(app, arguments, env=environment)


def _write_model(path: Path, model: BaseModel) -> Path:
    path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return path


def _save_job(cli: tuple[CliRunner, dict[str, str], Path], tmp_path: Path) -> str:
    result = _invoke(
        cli,
        [
            "jobs",
            "save",
            "--file",
            str(_write_model(tmp_path / "job.json", _job())),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    return str(json.loads(result.stdout)["id"])


def _create_application(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
    *,
    resume_version_id: str | None = None,
) -> str:
    saved_job_id = _save_job(cli, tmp_path)
    arguments = ["applications", "create", "--job", saved_job_id, "--json"]
    if resume_version_id:
        arguments.extend(["--resume-version", resume_version_id])
    result = _invoke(cli, arguments)
    assert result.exit_code == 0, result.output
    return str(json.loads(result.stdout)["id"])


def _seed_resume_version(database_path: Path) -> str:
    database = Database(f"sqlite:///{database_path.as_posix()}")
    database.initialize()
    masters = MasterResumeRepository(database)
    versions = ResumeVersionRepository(database)
    versioning = ResumeVersioningService(
        masters,
        versions,
        JobRepository(database),
    )
    request = _request()
    existing = masters.list_all()
    master = existing[0] if existing else versioning.save_master_resume(request.resume)
    result = FullResumeOptimizer(MockBulletRewriter(_safe_packet_rewrite)).optimize(request)
    return versioning.save_optimized_resume(master.id, result).id


def test_cli_help_works(cli: tuple[CliRunner, dict[str, str], Path]) -> None:
    result = _invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "applications" in result.stdout
    assert "jobs" in result.stdout


def test_save_job_from_json_with_analysis_and_ats(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    request = _request()
    result = _invoke(
        cli,
        [
            "jobs",
            "save",
            "--file",
            str(_write_model(tmp_path / "job.json", _job())),
            "--analysis-file",
            str(_write_model(tmp_path / "analysis.json", request.job_analysis)),
            "--ats-file",
            str(_write_model(tmp_path / "ats.json", request.ats_match_report)),
            "--json",
        ],
    )

    payload = json.loads(result.stdout)
    assert result.exit_code == 0
    assert payload["job_analysis"]["job_id"] == request.job_analysis.job_id
    assert payload["ats_score"] == request.ats_match_report.overall_score


def test_list_filter_show_and_show_json_for_saved_jobs(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    saved_job_id = _save_job(cli, tmp_path)

    listed = _invoke(cli, ["jobs", "list", "--company", "Example"])
    shown = _invoke(cli, ["jobs", "show", saved_job_id])
    json_result = _invoke(cli, ["jobs", "show", saved_job_id, "--json"])

    assert "SOC Analyst Intern" in listed.stdout
    assert "Example Security" in shown.stdout
    assert json.loads(json_result.stdout)["id"] == saved_job_id


def test_create_list_and_show_application(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    saved_job_id = _save_job(cli, tmp_path)
    created = _invoke(
        cli,
        [
            "applications",
            "create",
            "--job",
            saved_job_id,
            "--status",
            "READY_TO_APPLY",
            "--note",
            "Review complete.",
            "--json",
        ],
    )
    application_id = json.loads(created.stdout)["id"]

    listed = _invoke(cli, ["applications", "list", "--status", "READY_TO_APPLY"])
    shown = _invoke(cli, ["applications", "show", application_id])
    json_result = _invoke(cli, ["applications", "show", application_id, "--json"])

    assert application_id in listed.stdout
    assert "Review complete." in shown.stdout
    assert json.loads(json_result.stdout)["application"]["id"] == application_id


def test_create_and_link_application_resume_version(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    _, _, database_path = cli
    version_id = _seed_resume_version(database_path)
    application_id = _create_application(cli, tmp_path, resume_version_id=version_id)

    create_json = _invoke(cli, ["applications", "show", application_id, "--json"])
    assert json.loads(create_json.stdout)["application"]["resume_version_id"] == version_id

    second_version = _seed_resume_version(database_path)
    linked = _invoke(cli, ["applications", "link-resume", application_id, second_version])
    assert linked.exit_code == 0
    assert second_version in linked.stdout


def test_status_history_applied_timestamp_and_note(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    application_id = _create_application(cli, tmp_path)

    updated = _invoke(
        cli,
        [
            "applications",
            "status",
            application_id,
            "APPLIED",
            "--note",
            "Applied through Greenhouse.",
        ],
    )
    history = _invoke(cli, ["applications", "history", application_id])
    shown = _invoke(cli, ["applications", "show", application_id, "--json"])

    assert updated.exit_code == 0
    assert "PLANNED -> APPLIED" in history.stdout
    payload = json.loads(shown.stdout)
    assert payload["application"]["applied_at"]
    assert payload["notes"][0]["note"] == "Applied through Greenhouse."


def test_add_note_set_followup_and_list_due(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    application_id = _create_application(cli, tmp_path)

    note = _invoke(
        cli,
        ["applications", "note", application_id, "Recruiter replied.", "--type", "INTERVIEW"],
    )
    followup = _invoke(cli, ["applications", "followup", application_id, "2026-06-20"])
    due = _invoke(cli, ["applications", "due", "--as-of", "2026-06-20"])

    assert note.exit_code == 0
    assert followup.exit_code == 0
    assert application_id in due.stdout


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["applications", "followup", "missing", "not-a-date"], "Invalid date"),
        (["applications", "create", "--job", "missing"], "saved job was not found"),
        (
            ["applications", "create", "--job", "missing", "--status", "NOPE"],
            "Invalid application status",
        ),
        (["applications", "show", "missing"], "Application not found"),
        (["jobs", "show", "missing"], "Saved job not found"),
    ],
)
def test_expected_cli_errors_are_clear_without_tracebacks(
    cli: tuple[CliRunner, dict[str, str], Path],
    arguments: list[str],
    message: str,
) -> None:
    result = _invoke(cli, arguments)

    assert result.exit_code == 1
    assert message in result.output
    assert "Traceback" not in result.output


def test_malformed_and_missing_json_are_handled(
    cli: tuple[CliRunner, dict[str, str], Path],
    tmp_path: Path,
) -> None:
    malformed = tmp_path / "bad.json"
    malformed.write_text("{bad", encoding="utf-8")

    malformed_result = _invoke(cli, ["jobs", "save", "--file", str(malformed)])
    missing_result = _invoke(cli, ["jobs", "save", "--file", str(tmp_path / "missing.json")])

    assert malformed_result.exit_code == 1
    assert "Invalid JobPosting JSON" in malformed_result.output
    assert missing_result.exit_code == 1
    assert "JSON file not found" in missing_result.output


def test_cli_database_is_isolated(cli: tuple[CliRunner, dict[str, str], Path]) -> None:
    result = _invoke(cli, ["applications", "list", "--json"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == []
