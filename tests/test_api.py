"""FastAPI integration tests using isolated services and no live providers."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas  # type: ignore[import-untyped]

from ai_internship_assistant.api.dependencies import ApiContainer, build_container
from ai_internship_assistant.api.main import create_app
from ai_internship_assistant.config import AppSettings
from ai_internship_assistant.domain.models import JobPosting, Resume
from tests.test_application_tracking import _job
from tests.test_full_resume_optimizer import _resume


class StubResumeParser:
    """Deterministic upload parser used instead of an LLM."""

    def parse(self, text: str) -> Resume:
        assert text.strip()
        return _resume()


@pytest.fixture
def api(tmp_path: Path) -> tuple[TestClient, ApiContainer]:
    """Create one isolated API application and database."""

    settings = AppSettings(
        database_url=f"sqlite:///{(tmp_path / 'api.db').as_posix()}",
        resume_output_dir=str(tmp_path / "exports"),
    )
    container = build_container(settings=settings, resume_parser=StubResumeParser())
    return TestClient(create_app(container), raise_server_exceptions=False), container


def _seed_resume(container: ApiContainer) -> str:
    return container.versioning.save_master_resume(_resume()).id


def _seed_saved_job(container: ApiContainer, posting: JobPosting | None = None) -> str:
    return container.tracking.save_job(posting or _job()).id


def _pdf_bytes() -> bytes:
    target = BytesIO()
    document = canvas.Canvas(target)
    document.drawString(72, 720, "Alex Candidate Python Linux resume")
    document.save()
    return target.getvalue()


def _docx_bytes() -> bytes:
    target = BytesIO()
    with ZipFile(target, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" '
                'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                "</Types>"
            ),
        )
        archive.writestr(
            "_rels/.rels",
            (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                'relationships/officeDocument" '
                'Target="word/document.xml"/>'
                "</Relationships>"
            ),
        )
        archive.writestr(
            "word/document.xml",
            (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>Alex Candidate Python Linux resume</w:t>"
                "</w:r></w:p></w:body></w:document>"
            ),
        )
    return target.getvalue()


def test_health_and_dependency_health(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    assert client.get("/health").json()["status"] == "ok"
    dependencies = client.get("/health/dependencies")

    assert dependencies.status_code == 200
    assert dependencies.json()["database"] == "ok"


def test_upload_rejects_unsupported_file_type(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    response = client.post(
        "/resumes/upload",
        files={"file": ("resume.exe", b"MZ", "application/octet-stream")},
    )

    assert response.status_code == 415


@pytest.mark.parametrize(
    ("filename", "content"),
    [("resume.pdf", _pdf_bytes()), ("resume.docx", _docx_bytes())],
)
def test_upload_resume_and_list_detail(
    api: tuple[TestClient, ApiContainer],
    filename: str,
    content: bytes,
) -> None:
    client, _ = api

    uploaded = client.post("/resumes/upload", files={"file": (filename, content)})
    payload = uploaded.json()

    assert uploaded.status_code == 201
    assert payload["resume_id"]
    assert client.get("/resumes").json()[0]["resume_id"] == payload["resume_id"]
    detail = client.get(f"/resumes/{payload['resume_id']}")
    assert detail.status_code == 200
    assert detail.json()["candidate_name"] == "Alex Candidate"


def test_missing_resume_returns_404_without_traceback(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    response = client.get("/resumes/missing")

    assert response.status_code == 404
    assert "Traceback" not in response.text


def test_resume_versions_list_is_empty(api: tuple[TestClient, ApiContainer]) -> None:
    client, container = api
    resume_id = _seed_resume(container)

    response = client.get(f"/resumes/{resume_id}/versions")

    assert response.status_code == 200
    assert response.json() == []


def test_search_jobs_and_missing_resume(api: tuple[TestClient, ApiContainer]) -> None:
    client, container = api
    resume_id = _seed_resume(container)

    response = client.post(
        "/jobs/search",
        json={"resume_id": resume_id, "max_results": 5, "save_results": True},
    )
    missing = client.post("/jobs/search", json={"resume_id": "missing"})

    assert response.status_code == 200
    assert response.json()["query_count"] > 0
    assert client.get("/jobs/saved").status_code == 200
    assert missing.status_code == 404


def test_saved_job_list_detail_and_analysis(api: tuple[TestClient, ApiContainer]) -> None:
    client, container = api
    saved_job_id = _seed_saved_job(container)

    saved = client.get("/jobs/saved").json()[0]
    detail = client.get(f"/jobs/saved/{saved_job_id}")
    assert saved["id"] == saved_job_id
    assert "raw_data" not in saved["job"]
    assert detail.status_code == 200
    assert "raw_data" not in detail.json()["job"]
    analysis = client.post(f"/jobs/{saved_job_id}/analyze")

    assert analysis.status_code == 200
    assert analysis.json()["job_id"] == "soc-job"


def test_optimization_plan_run_versions_and_exports(api: tuple[TestClient, ApiContainer]) -> None:
    client, container = api
    resume_id = _seed_resume(container)
    saved_job_id = _seed_saved_job(container)

    plan = client.post(
        "/optimization/plan",
        json={"resume_id": resume_id, "saved_job_id": saved_job_id},
    )
    run = client.post(
        "/optimization/run",
        json={
            "resume_id": resume_id,
            "saved_job_id": saved_job_id,
            "export_formats": ["markdown", "docx", "pdf"],
        },
    )

    assert plan.status_code == 200
    assert plan.json()["plan_id"] is None
    assert run.status_code == 200
    payload = run.json()
    assert len(payload["exported_files"]) == 3
    version_id = payload["resume_version_id"]
    assert client.get(f"/resumes/{resume_id}/versions").json()
    assert client.get(f"/resumes/versions/{version_id}").status_code == 200

    export = client.post(
        f"/exports/resume-version/{version_id}",
        json={"formats": ["markdown"]},
    )
    file_id = export.json()["exported_files"][0]["file_id"]
    assert client.get(f"/exports/files/{file_id}").status_code == 200


def test_download_rejects_invalid_file_id(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    response = client.get("/exports/files/../../secret")

    assert response.status_code == 404


def test_application_routes(api: tuple[TestClient, ApiContainer]) -> None:
    client, container = api
    saved_job_id = _seed_saved_job(container)

    created = client.post("/applications", json={"saved_job_id": saved_job_id, "note": "Plan"})
    application_id = created.json()["id"]

    assert created.status_code == 201
    assert client.get("/applications").json()[0]["id"] == application_id
    status = client.patch(
        f"/applications/{application_id}/status",
        json={"status": "applied", "note": "Applied."},
    )
    assert status.json()["applied_at"]
    note = client.post(
        f"/applications/{application_id}/notes",
        json={"note": "Recruiter replied.", "note_type": "interview"},
    )
    assert note.status_code == 201
    follow_up = client.patch(
        f"/applications/{application_id}/follow-up",
        json={"follow_up_date": "2026-06-20"},
    )
    assert follow_up.status_code == 200
    assert client.get("/applications/due?as_of=2026-06-20").json()[0]["id"] == application_id
    detail = client.get(f"/applications/{application_id}")
    assert detail.status_code == 200
    assert len(detail.json()["status_history"]) == 2


def test_application_missing_maps_to_404(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    response = client.get("/applications/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "application was not found"


def test_each_api_test_uses_isolated_database(api: tuple[TestClient, ApiContainer]) -> None:
    client, _ = api

    assert client.get("/resumes").json() == []
    assert client.get("/applications").json() == []
