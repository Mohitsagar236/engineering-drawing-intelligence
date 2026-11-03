"""Exercise a running API + worker with real OCR on a synthetic PDF."""

import argparse
import json
import os
import time
import pymupdf as fitz
import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--url", default="http://localhost:8000")
args = parser.parse_args()
with fitz.open() as pdf:
    page = pdf.new_page(width=700, height=400)
    for i, line in enumerate(
        ["ASBESTOS CEMENT BOARD", "VINYL FLOOR TILE", "GLASS WOOL INSULATION"]
    ):
        page.insert_text((40, 80 + i * 100), line, fontsize=24)
    content = pdf.tobytes()
with httpx.Client(base_url=args.url, timeout=30) as client:
    if os.environ.get("ED_SMOKE_PASSWORD"):
        session = client.post(
            "/api/session",
            json={
                "username": os.environ.get("ED_SMOKE_USERNAME", "reviewer"),
                "password": os.environ["ED_SMOKE_PASSWORD"],
            },
        )
        session.raise_for_status()
    upload = client.post(
        "/api/documents/upload",
        files={"file": ("synthetic-plan.pdf", content, "application/pdf")},
    )
    upload.raise_for_status()
    document = upload.json()
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        doc = client.get(f"/api/documents/{document['id']}").json()
        if doc["status"] in ("COMPLETE", "FAILED"):
            break
        time.sleep(1)
    assert doc["status"] == "COMPLETE", doc
    results = client.get(f"/api/documents/{doc['id']}/results").json()
    materials = [f for f in results["findings"] if f["is_material"]]
    assert len(materials) == 3, results
    assert all(f["classification"] == "MANUAL_REVIEW" for f in materials), materials
    assert (
        client.get(f"/api/documents/{doc['id']}/pages/1").headers["content-type"]
        == "image/png"
    )
    pdf = client.get(f"/api/documents/{doc['id']}/report")
    assert pdf.content.startswith(b"%PDF"), pdf.text
    assert (
        client.get(f"/api/documents/{doc['id']}/report?format=csv").status_code == 200
    )
    print(
        json.dumps(
            {
                "document_id": doc["id"],
                "job_id": results["job"]["id"],
                "ocr_annotations": len(results["findings"]),
                "material_findings": len(materials),
                "classifications": [f["classification"] for f in materials],
                "pdf_bytes": len(pdf.content),
                "status": "PASS",
            },
            indent=2,
        )
    )
