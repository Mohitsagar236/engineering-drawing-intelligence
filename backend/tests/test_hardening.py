import io
import pytest
import pymupdf as fitz
from PIL import Image
from app.core.config import settings
from app.services.processing import process
from app.services.materials import analyze


def test_multipart_streaming_body_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    chunks = iter(
        [
            b'--ed-boundary\r\nContent-Disposition: form-data; name="file"; filename="big.png"\r\nContent-Type: image/png\r\n\r\n',
            b"x" * (2 * 1024 * 1024),
            b"\r\n--ed-boundary--\r\n",
        ]
    )
    response = client.post(
        "/api/documents",
        content=chunks,
        headers={"Content-Type": "multipart/form-data; boundary=ed-boundary"},
    )
    assert response.status_code == 413, response.text


def test_huge_pdf_page_is_rejected_before_rendering(client):
    with fitz.open() as pdf:
        pdf.new_page(width=20000, height=20000)
        response = client.post(
            "/api/documents",
            files={"file": ("huge.pdf", pdf.tobytes(), "application/pdf")},
        )
    assert response.status_code == 422


def test_comparison_exposes_completed_runs(client, monkeypatch):
    content = io.BytesIO()
    Image.new("RGB", (100, 100), "white").save(content, format="PNG")
    data = client.post(
        "/api/documents", files={"file": ("plan.png", content.getvalue(), "image/png")}
    ).json()
    monkeypatch.setattr("app.services.processing.recognize_image", lambda *args: [])
    process(data["job"]["id"])
    response = client.post("/api/ocr/compare", json={"document_id": data["id"]})
    assert response.status_code == 200, response.text
    assert response.json()["engines"]["easyocr"]["job"]["status"] == "COMPLETE"
    assert response.json()["engines"]["paddleocr"] is None


@pytest.mark.parametrize("confidence", [float("nan"), float("inf"), 1.1, -0.1])
def test_invalid_ocr_confidence_cannot_classify(db, confidence):
    from app.models.models import Material

    db.add(
        Material(
            standard_name="TEST MATERIAL",
            source="Synthetic reference certificate for a test",
            verification_status="VERIFIED",
            asbestos_status="DOES_NOT_CONTAIN_ASBESTOS",
        )
    )
    db.commit()
    assert analyze(db, "TEST MATERIAL", confidence)["classification"] == "MANUAL_REVIEW"
