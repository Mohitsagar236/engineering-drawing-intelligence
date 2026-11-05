"""Regression coverage for deployment and data integrity failures."""

import os
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import event

from app.core.auth import attempts
from app.core.config import settings
from app.db.session import engine
from app.models.models import Document, Job
from app.services.processing import process
from app import worker
from test_api import upload, image_bytes


@pytest.mark.parametrize(
    "path,payload",
    [
        ("/api/materials", {"standard_name": "   "}),
        (
            "/api/reviews",
            {
                "finding_id": 1,
                "classification": "NON_ASBESTOS",
                "reason": " " * 12,
                "source": " " * 12,
            },
        ),
    ],
)
def test_whitespace_is_not_evidence(client, path, payload):
    assert client.post(path, json=payload).status_code == 422


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"standard_name\n",
        b"name\nProduct\n",
        b"standard_name,standard_name\na,b\n",
    ],
)
def test_empty_or_invalid_csv_is_rejected(client, content):
    assert (
        client.post(
            "/api/materials/import",
            files={"file": ("catalog.csv", content, "text/csv")},
        ).status_code
        == 422
    )


def test_csv_import_reports_duplicates(client):
    payload = {"file": ("catalog.csv", b"standard_name\nProduct One\n", "text/csv")}
    assert client.post("/api/materials/import", files=payload).json()["imported"] == 1
    result = client.post("/api/materials/import", files=payload).json()
    assert result["imported"] == 0 and result["skipped"] == 1


@pytest.mark.parametrize("name", ["disguised.jpg", "disguised.pdf"])
def test_upload_extension_must_match_content(client, name):
    assert (
        client.post(
            "/api/documents", files={"file": (name, image_bytes(), "image/png")}
        ).status_code
        == 422
    )


def test_missing_original_returns_conflict(client, db, monkeypatch):
    data = upload(client)
    monkeypatch.setattr("app.services.processing.recognize_image", lambda *args: [])
    process(data["job"]["id"])
    Path(db.get(Job, data["job"]["id"]).path).unlink()
    assert (
        client.post(f"/api/documents/{data['id']}/process", json={}).status_code == 409
    )
    assert client.get(f"/api/documents/{data['id']}").json()["status"] == "COMPLETE"


def test_readiness_detects_stale_or_missing_worker(client):
    path = Path(settings.upload_dir) / ".worker-heartbeat"
    path.unlink(missing_ok=True)
    assert client.get("/api/ready").status_code == 503
    worker.heartbeat()
    assert client.get("/api/ready").json()["worker"] is True
    os.utime(path, (time.time() - 20, time.time() - 20))
    assert client.get("/api/ready").status_code == 503
    assert client.get("/api/health").status_code == 200


def test_basic_credentials_are_rate_limited(client, monkeypatch):
    attempts.clear()
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    for _ in range(10):
        assert (
            client.get("/api/documents", auth=("reviewer", "wrong")).status_code == 401
        )
    response = client.get("/api/documents", auth=("reviewer", "wrong"))
    assert response.status_code == 429 and response.headers["retry-after"] == "60"
    assert (
        client.get(
            "/api/documents", auth=("reviewer", "a-long-test-password")
        ).status_code
        == 200
    )
    attempts.clear()


def test_document_pagination_uses_bounded_queries(client, db):
    for i in range(205):
        document = Document(
            filename=f"drawing-{i}.png", pages=1, content_type="image/png"
        )
        db.add(document)
        db.flush()
        db.add(Job(document_id=document.id, path="fixture.png", engine="easyocr"))
    db.commit()
    statements = []

    def record(*args):
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        first = client.get("/api/documents?limit=200").json()
    finally:
        event.remove(engine, "before_cursor_execute", record)
    second = client.get("/api/documents?limit=200&offset=200").json()
    assert len(first) == 200 and len(second) == 5
    assert set(d["id"] for d in first).isdisjoint(d["id"] for d in second)
    # Count, page of documents, and one batched tag load: independent of page size.
    assert len(statements) == 3


def test_worker_reaps_inference_on_shutdown(monkeypatch, tmp_path):
    child = Mock(pid=987654)
    child.wait.side_effect = [SystemExit(0), 0]
    child.poll.return_value = None
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=child))
    kill = Mock()
    failed = Mock()
    monkeypatch.setattr(worker.os, "killpg", kill)
    monkeypatch.setattr(worker, "fail", failed)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    with pytest.raises(SystemExit):
        worker.execute_job(42)
    kill.assert_called_once_with(child.pid, worker.signal.SIGTERM)
    failed.assert_called_once_with(
        42, "Worker stopped during processing; retry analysis."
    )
    assert child.wait.call_count == 2


def test_worker_escalates_when_inference_ignores_shutdown(monkeypatch, tmp_path):
    import subprocess

    child = Mock(pid=987654)
    child.wait.side_effect = [SystemExit(0), subprocess.TimeoutExpired("ocr", 5), 0]
    child.poll.return_value = None
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=child))
    kill = Mock()
    monkeypatch.setattr(worker.os, "killpg", kill)
    monkeypatch.setattr(worker, "fail", Mock())
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    with pytest.raises(SystemExit):
        worker.execute_job(42)
    assert [call.args[1] for call in kill.call_args_list] == [
        worker.signal.SIGTERM,
        worker.signal.SIGKILL,
    ]


def test_worker_timeout_terminates_before_marking_failed(monkeypatch, tmp_path):
    child = Mock(pid=987654)
    child.poll.return_value = None
    monkeypatch.setattr(worker.subprocess, "Popen", Mock(return_value=child))
    clock = iter([0, settings.processing_timeout + 1])
    monkeypatch.setattr(worker.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(worker.os, "killpg", Mock())
    failed = Mock()
    monkeypatch.setattr(worker, "fail", failed)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))
    worker.execute_job(42)
    child.wait.assert_called_once_with(timeout=5)
    assert "exceeded configured timeout" in failed.call_args.args[1]


def test_invalid_ocr_output_is_not_persisted(client, db, monkeypatch):
    data = upload(client)
    monkeypatch.setattr(
        "app.services.processing.recognize_image",
        lambda *args: [
            ("floor tile", float("inf"), [[0, 0], [1, 0], [1, 1], [0, 1]], "test")
        ],
    )
    with pytest.raises(ValueError, match="invalid confidence"):
        process(data["job"]["id"])
    assert client.get(f"/api/documents/{data['id']}/results").json()["findings"] == []


@pytest.mark.parametrize("value", ["=SUM(1,2)", "  =SUM(1,2)", "\n=1+1", "\t@SUM(1)"])
def test_csv_exports_escape_formulas_after_whitespace(value):
    import csv
    import io
    from app.main import csv_response

    response = csv_response([[value]], "test.csv")
    row = next(csv.reader(io.StringIO(response.body.decode())))
    assert row[0] == "'" + value


def test_unauthorized_responses_cannot_be_cached(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    response = client.get("/api/documents")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "https://*.example.com",
        "http://localhost:3000",
        "https://example.com/path",
        "https://user:password@example.com",
    ],
)
def test_production_rejects_unsafe_origins(origin):
    from app.core.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="HTTPS origins"):
        Settings(
            _env_file=None,
            environment="production",
            auth_password="long-enough-password",
            cors_origins=origin,
        )


def test_production_requires_authentication():
    from app.core.config import Settings
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="AUTH_PASSWORD"):
        Settings(
            _env_file=None,
            environment="production",
            auth_password="",
            cors_origins="https://drawings.example.com",
        )
    assert (
        Settings(
            _env_file=None,
            environment="production",
            auth_password="long-enough-password",
            cors_origins="https://drawings.example.com",
        ).environment
        == "production"
    )


def test_logout_revokes_a_copied_session(client, monkeypatch):
    attempts.clear()
    monkeypatch.setattr(settings, "auth_password", "a-long-test-password")
    assert (
        client.post(
            "/api/session",
            json={"username": "reviewer", "password": "a-long-test-password"},
        ).status_code
        == 200
    )
    token = client.cookies.get("ed_session")
    assert client.delete("/api/session").status_code == 200
    client.cookies.set("ed_session", token)
    assert client.get("/api/documents").status_code == 401
    assert client.get("/api/session").json()["authenticated"] is False


def test_login_body_is_bounded_before_validation(client):
    attempts.clear()
    result = client.post(
        "/api/session",
        json={"username": "reviewer", "password": "x" * (2 * 1024 * 1024)},
    )
    assert result.status_code == 413
    assert len(result.content) < 1000


def test_invalid_login_payloads_are_throttled_and_not_reflected(client):
    attempts.clear()
    for _ in range(10):
        response = client.post(
            "/api/session",
            json={"username": "reviewer", "password": "private-value" * 100},
        )
        assert response.status_code == 422
        assert "private-value" not in response.text
    assert client.post("/api/session", json={}).status_code == 429
    attempts.clear()


@pytest.mark.parametrize(
    "text", ["石綿", "アスベスト含有", "配管保温材", "ロックウール断熱材"]
)
def test_unmatched_japanese_materials_remain_visible(text):
    from app.services.materials import analyze, is_material

    result = analyze(None, text, 0.99, records=[])
    assert result["classification"] == "MANUAL_REVIEW"
    assert is_material(text, result)


def test_interrupted_analysis_cannot_publish_complete(client, db, monkeypatch):
    from app.db.session import SessionLocal

    data = upload(client)

    def interrupt(*args):
        with SessionLocal() as other:
            other.get(Job, data["job"]["id"]).status = "FAILED"
            other.get(Document, data["id"]).status = "FAILED"
            other.commit()
        return []

    monkeypatch.setattr("app.services.processing.recognize_image", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        process(data["job"]["id"])
    assert client.get(f"/api/documents/{data['id']}").json()["status"] == "FAILED"


def test_orphan_monitor_stops_inference_when_parent_disappears(monkeypatch):
    exit_process = Mock(side_effect=SystemExit(1))
    monkeypatch.setattr(worker.os, "getppid", lambda: 1)
    monkeypatch.setattr(worker.os, "_exit", exit_process)
    with pytest.raises(SystemExit):
        worker.watch_dispatcher(123)
    exit_process.assert_called_once_with(1)
