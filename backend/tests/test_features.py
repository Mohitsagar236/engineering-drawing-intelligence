import json
from app.models.models import Document, Finding, Evidence, Job, Page
from app.services.extraction import extract


def box(x, y, w=80, h=20):
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def make_doc(db, name="a.png", project_id=None, texts=(), status="COMPLETE"):
    doc = Document(
        filename=name,
        content_type="image/png",
        pages=1,
        status=status,
        project_id=project_id,
    )
    db.add(doc)
    db.flush()
    job = Job(document_id=doc.id, path="x.png", engine="easyocr", status=status)
    db.add(job)
    db.flush()
    db.add(Page(job_id=job.id, number=1, width=1000, height=800, path="p.png"))
    for text, material in texts:
        f = Finding(
            document_id=doc.id,
            page=1,
            source_text=text,
            normalized_name=text,
            classification="MANUAL_REVIEW",
            confidence=0.9,
            bbox=json.dumps(box(0, 0)),
        )
        db.add(f)
        db.flush()
        db.add(
            Evidence(
                finding_id=f.id,
                job_id=job.id,
                is_material=int(material),
                explanation="e",
                reference_snapshot='{"category": "Gasket"}',
            )
        )
    db.commit()
    return doc


def test_projects_tags_and_filtering(client, db):
    project = client.post("/api/projects", json={"name": "Plant A"}).json()
    assert client.post("/api/projects", json={"name": "Plant A"}).status_code == 409
    one = make_doc(db, "pump.png", texts=[("Gasket 1234", True)])
    two = make_doc(db, "valve.png")
    patched = client.patch(
        f"/api/documents/{one.id}",
        json={"project_id": project["id"], "tags": ["Urgent", " urgent ", "Site 2"]},
    ).json()
    assert (
        patched["tags"] == ["site 2", "urgent"]
        and patched["project_id"] == project["id"]
    )
    assert (
        client.patch(f"/api/documents/{two.id}", json={"project_id": 999}).status_code
        == 404
    )

    def ids(query):
        r = client.get("/api/documents" + query)
        return [d["id"] for d in r.json()], r.headers["X-Total-Count"]

    assert ids(f"?project_id={project['id']}")[0] == [one.id]
    assert ids("?project_id=-1")[0] == [two.id]
    assert ids("?tag=URGENT")[0] == [one.id]
    assert ids("?q=gasket")[0] == [one.id]  # OCR text search
    assert ids("?q=valve")[0] == [two.id]  # filename search
    assert ids("?q=%25") == ([], "0")  # wildcard characters are literal
    assert ids("?status=failed")[0] == []
    assert [t["name"] for t in client.get("/api/tags").json()] == ["site 2", "urgent"]
    assert client.get("/api/projects").json()[0]["documents"] == 1
    assert client.delete(f"/api/projects/{project['id']}").status_code == 204
    assert ids("?project_id=-1")[1] == "2"


def test_project_summary_batch_reports_and_audit(client, db):
    project = client.post("/api/projects", json={"name": "Plant B"}).json()
    done = make_doc(db, "done.png", project["id"], [("Gasket", True), ("note", False)])
    make_doc(db, "queued.png", project["id"], status="QUEUED")
    summary = client.get(f"/api/projects/{project['id']}/summary").json()
    assert summary["documents"] == 2 and summary["materials"] == 1
    assert summary["classifications"]["MANUAL_REVIEW"] == 1
    assert summary["processing"]["QUEUED"] == 1

    batch = client.get(f"/api/reports/batch?ids={done.id},{done.id + 1}&format=csv")
    assert batch.status_code == 200
    assert batch.headers["X-Skipped-Documents"] == str(done.id + 1)
    assert batch.text.splitlines()[0].startswith("document_id,filename,page")
    assert "done.png" in batch.text and "queued.png" not in batch.text
    zipped = client.get(f"/api/reports/batch?ids={done.id}&format=pdf")
    assert zipped.content[:2] == b"PK"
    assert client.get("/api/reports/batch?ids=abc").status_code == 422
    assert client.get(f"/api/reports/batch?ids={done.id + 1}").status_code == 409
    assert (
        client.get(f"/api/projects/{project['id']}/report?format=pdf").content[:4]
        == b"%PDF"
    )
    assert (
        "done.png"
        in client.get(f"/api/projects/{project['id']}/report?format=csv").text
    )
    assert client.get(f"/api/reports/{done.id}?format=csv").status_code == 200

    actions = client.get("/api/audit/filters").json()["actions"]
    assert "project.create" in actions
    filtered = client.get("/api/audit?action=project.create")
    assert filtered.headers["X-Total-Count"] == "1"
    assert filtered.json()[0]["action"] == "project.create"
    assert client.get("/api/audit?q=Plant+B").json()
    assert client.get("/api/audit?offset=-1").status_code == 422


def f(i, text, x, y, w=80):
    return dict(id=i, page=1, source_text=text, confidence=0.9, bbox=box(x, y, w))


def test_extraction_title_block_dimensions_and_bom():
    pages = [dict(number=1, width=1000, height=800)]
    findings = [
        f(1, "DRAWING NO:", 600, 700),
        f(2, "PMP-1001", 700, 700),
        f(3, "SCALE 1:2", 600, 730),
        f(4, "TITLE", 600, 760),
        f(5, "Pump housing", 600, 782),
        f(6, "Ø25.4", 100, 100),
        f(7, "R5", 200, 100),
        f(8, "M8", 300, 100),
        f(9, "45°", 400, 100),
        f(10, "120 ±0.5 mm", 100, 200, 120),
        f(11, "Hello world", 100, 300),
        f(20, "ITEM", 50, 400, 40),
        f(21, "QTY", 150, 400, 40),
        f(22, "DESCRIPTION", 250, 400, 120),
        f(23, "MATERIAL", 450, 400, 90),
        f(30, "1", 50, 430, 40),
        f(31, "2", 150, 430, 40),
        f(32, "Gasket", 250, 430, 120),
        f(33, "Graphite", 450, 430, 90),
        f(34, "2", 50, 460, 40),
        f(35, "4", 150, 460, 40),
        f(36, "Bolt", 250, 460, 120),
        f(37, "Steel", 450, 460, 90),
    ]
    data = extract(findings, pages)
    fields = {e["field"]: e["value"] for e in data["title_block"]}
    assert fields["drawing_number"] == "PMP-1001"
    assert fields["scale"] == "1:2"
    assert fields["title"] == "Pump housing"
    kinds = {d["text"]: d for d in data["dimensions"]}
    assert kinds["Ø25.4"]["kind"] == "diameter" and kinds["Ø25.4"]["value"] == 25.4
    assert kinds["R5"]["kind"] == "radius"
    assert kinds["M8"]["kind"] == "thread"
    assert kinds["45°"]["kind"] == "angle"
    assert kinds["120 ±0.5 mm"]["tolerance"].startswith("±")
    assert "Hello world" not in kinds
    (table,) = data["bom"]
    assert table["columns"] == ["item", "quantity", "description", "material"]
    assert table["rows"][0]["cells"] == {
        "item": "1",
        "quantity": "2",
        "description": "Gasket",
        "material": "Graphite",
    }
    assert table["rows"][1]["cells"]["description"] == "Bolt"


def test_extraction_endpoint(client, db):
    doc = make_doc(db, texts=[("SCALE 1:5", False), ("Ø10", False)])
    data = client.get(f"/api/documents/{doc.id}/extraction").json()
    assert data["title_block"][0]["value"] == "1:5"
    assert data["dimensions"][0]["kind"] == "diameter"
    csv = client.get(f"/api/documents/{doc.id}/extraction?format=csv")
    assert "title_block" in csv.text and "dimension" in csv.text
    queued = make_doc(db, "q.png", status="QUEUED")
    assert client.get(f"/api/documents/{queued.id}/extraction").status_code == 409
