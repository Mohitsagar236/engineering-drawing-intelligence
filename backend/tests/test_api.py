import io
import pymupdf as fitz
from PIL import Image
from app.models.models import Job
from app.services.processing import process
from app.services.ocr import preprocess, polygon
from app.core.config import settings


def image_bytes():
    out = io.BytesIO()
    Image.new("RGB", (400, 200), "white").save(out, format="PNG")
    return out.getvalue()


def upload(client):
    result = client.post(
        "/api/documents/upload",
        files={"file": ("drawing.png", image_bytes(), "image/png")},
    )
    assert result.status_code == 202, result.text
    return result.json()


def test_image_upload_and_background_status(client, db):
    data = upload(client)
    assert data["status"] == "QUEUED" and data["pages"] == 1
    assert db.query(Job).count() == 1
    assert client.get("/api/documents").json()[0]["id"] == data["id"]


def test_pdf_upload_and_page_limit(client):
    with fitz.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        result = client.post(
            "/api/documents",
            files={"file": ("drawing.pdf", pdf.tobytes(), "application/pdf")},
        )
    assert result.status_code == 202
    assert result.json()["pages"] == 2


def test_corrupt_and_unsupported_uploads(client):
    assert (
        client.post(
            "/api/documents", files={"file": ("bad.png", b"garbage", "image/png")}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/documents",
            files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
        ).status_code
        == 415
    )
    assert (
        client.post(
            "/api/documents", files={"file": ("empty.pdf", b"", "application/pdf")}
        ).status_code
        == 422
    )


def test_size_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    assert (
        client.post(
            "/api/documents",
            files={"file": ("big.png", b"x" * (1024 * 1024 + 1), "image/png")},
        ).status_code
        == 413
    )


def test_processing_persists_evidence_boxes_and_reports(client, db, monkeypatch):
    data = upload(client)
    monkeypatch.setattr(
        "app.services.processing.recognize_image",
        lambda *args: [
            (
                "vinyl floor tile",
                0.98,
                [[1, 2], [200, 2], [200, 40], [1, 40]],
                "test-engine",
            )
        ],
    )
    process(data["job"]["id"])
    result = client.get(f"/api/documents/{data['id']}/results").json()
    assert result["job"]["status"] == "COMPLETE"
    assert result["pages"][0]["width"] == 400
    assert result["findings"][0]["classification"] == "MANUAL_REVIEW"
    assert result["findings"][0]["engine"] == "test-engine"
    assert result["findings"][0]["bbox"] == [[1, 2], [200, 2], [200, 40], [1, 40]]
    assert (
        client.get(f"/api/documents/{data['id']}/pages/1").headers["content-type"]
        == "image/png"
    )
    pdf = client.get(f"/api/documents/{data['id']}/report")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    with fitz.open(stream=pdf.content, filetype="pdf") as report:
        assert len(report) >= 1
    assert (
        client.get(f"/api/documents/{data['id']}/report?format=csv").status_code == 200
    )
    stats = client.get("/api/dashboard/stats").json()
    assert stats["classifications"]["MANUAL_REVIEW"] == 1
    finding = result["findings"][0]
    review = client.post(
        "/api/reviews",
        json={
            "finding_id": finding["id"],
            "classification": "NON_ASBESTOS",
            "reason": "Laboratory sample confirmed negative",
            "source": "Independent laboratory certificate 2026-123",
        },
    )
    assert review.status_code == 201, review.text
    updated = client.get(f"/api/documents/{data['id']}/results").json()["findings"][0]
    assert updated["classification"] == "MANUAL_REVIEW"
    assert updated["review"]["classification"] == "NON_ASBESTOS"
    assert len(client.get("/api/audit").json()) >= 2


def test_reprocessing_preserves_previous_analysis(client, monkeypatch):
    data = upload(client)
    monkeypatch.setattr("app.services.processing.recognize_image", lambda *args: [])
    process(data["job"]["id"])
    result = client.post(
        f"/api/documents/{data['id']}/process",
        json={"engine": "easyocr", "contrast": True},
    )
    assert result.status_code == 202, result.text
    assert result.json()["job"]["id"] != data["job"]["id"]
    assert len(client.get(f"/api/documents/{data['id']}/history").json()) == 2
    assert (
        client.get(
            f"/api/documents/{data['id']}/report?job_id={data['job']['id']}"
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/documents/{data['id']}/process", json={"engine": "easyocr"}
        ).status_code
        == 409
    )


def test_reference_csv_import_downgrades_trust(client):
    data = b"standard_name,source,verification_status\nProduct Y,Certificate number 123,VERIFIED\n"
    response = client.post(
        "/api/materials/import", files={"file": ("materials.csv", data, "text/csv")}
    )
    assert response.status_code == 200, response.text
    record = next(
        m
        for m in client.get("/api/materials").json()
        if m["standard_name"] == "Product Y"
    )
    assert record["verification_status"] == "UNVERIFIED"
    assert client.get("/api/materials/export").status_code == 200


def test_verified_reference_requires_source(client):
    assert (
        client.post(
            "/api/materials",
            json={"standard_name": "Product Z", "verification_status": "VERIFIED"},
        ).status_code
        == 422
    )


def test_missing_document_and_report_incomplete(client):
    assert client.get("/api/documents/99999").status_code == 404
    data = upload(client)
    assert client.get(f"/api/documents/{data['id']}/report").status_code == 409


def test_basic_auth_protects_api(client, monkeypatch):
    monkeypatch.setattr(settings, "auth_password", "long-secret-for-test")
    assert client.get("/api/documents").status_code == 401
    assert (
        client.get(
            "/api/documents", auth=("reviewer", "long-secret-for-test")
        ).status_code
        == 200
    )
    assert client.get("/api/health").status_code == 200


def test_geometry_unchanged_by_preprocessing():
    original = Image.new("RGB", (400, 200), "white")
    assert preprocess(
        original, {"contrast": True, "denoise": True, "threshold": True}
    ).shape == (200, 400)
    assert polygon([1, 2, 3, 4]) == [[1, 2], [3, 2], [3, 4], [1, 4]]


def test_ocr_failure_is_not_empty_success(monkeypatch):
    from app.services.ocr import recognize_image

    monkeypatch.setattr(
        "app.services.ocr.available_engines",
        lambda: {"easyocr": False, "paddleocr": False},
    )
    import pytest

    with pytest.raises(RuntimeError, match="No OCR engine"):
        recognize_image(Image.new("RGB", (100, 100)), "auto", {})


def test_cross_origin_write_rejected(client):
    assert (
        client.post(
            "/api/materials",
            headers={"Origin": "https://untrusted.example"},
            json={"standard_name": "Product A"},
        ).status_code
        == 403
    )
