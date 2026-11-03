import base64
import csv
import io
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.core.config import settings
from app.core.uploads import UploadBodyLimit
from app.db.session import Base, engine, get_db, SessionLocal
from app.models.models import (
    Document,
    Finding,
    Material,
    Job,
    Page,
    Evidence,
    Review,
    Audit,
)
from app.schemas.api import ProcessIn, MaterialIn, ReviewIn, CompareIn, LoginIn
from app.core.auth import (
    COOKIE,
    create_session,
    session_actor,
    check_password,
    throttled,
    failed_login,
)
from app.services.materials import seed
from app.services.ocr import inspect_file, available_engines

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    if settings.environment == "production" and len(settings.auth_password) < 16:
        raise RuntimeError(
            "Production requires AUTH_PASSWORD of at least 16 characters"
        )
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    if settings.environment != "production":
        Base.metadata.create_all(engine)
    with SessionLocal() as db:
        # Revoke unsafe legacy demo verification without changing actual sourced records.
        for material in db.scalars(select(Material)):
            if material.source.startswith("Local reference"):
                material.verification_status = "DEMONSTRATION"
                material.source = (
                    "DEMONSTRATION ONLY; legacy seed is not verified evidence"
                )
        db.commit()
        seed(db)
    yield


app = FastAPI(
    title="Engineering Drawing Intelligence", version="0.2.0", lifespan=lifespan
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(UploadBodyLimit)


@app.middleware("http")
async def security(request: Request, call_next):
    started = time.perf_counter()
    request_id = secrets.token_hex(8)
    request.state.actor = "local-developer"
    if settings.auth_password and request.url.path not in (
        "/api/health",
        "/api/session",
    ):
        actor = session_actor(request.cookies.get(COOKIE, ""))
        try:
            kind, encoded = request.headers.get("Authorization", "").split(" ", 1)
            user, password = (
                base64.b64decode(encoded, validate=True).decode().split(":", 1)
            )
            valid = kind.lower() == "basic" and check_password(user, password)
        except (ValueError, UnicodeError):
            valid = False
        valid = valid or bool(actor)
        if not valid:
            return Response(
                status_code=401,
                headers={"WWW-Authenticate": 'Basic realm="Drawing Intelligence"'},
            )
        request.state.actor = actor or user
    if request.method in ("POST", "PUT", "DELETE") and request.headers.get("origin"):
        if request.headers["origin"] not in settings.cors_origin_list:
            return JSONResponse({"detail": "Origin is not permitted"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Request-ID"] = request_id
    logger.info(
        json.dumps(
            {
                "event": "request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
    )
    return response


@app.exception_handler(IntegrityError)
async def conflicting_write(request: Request, exception: IntegrityError):
    return JSONResponse(
        {
            "detail": "This update conflicts with an existing record. Refresh and try again."
        },
        status_code=409,
    )


def audit(db, request, action, entity_id, payload):
    db.add(
        Audit(
            actor=request.state.actor,
            action=action,
            entity_id=entity_id,
            payload=json.dumps(payload, default=str),
        )
    )


def document_or_404(db, document_id):
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def latest_job(db, document_id):
    return db.scalar(
        select(Job).where(Job.document_id == document_id).order_by(Job.id.desc())
    )


def serial_job(job):
    if not job:
        return None
    return dict(
        id=job.id,
        engine=job.engine,
        status=job.status,
        error=job.error,
        preprocessing=json.loads(job.preprocessing),
        runtime_config=json.loads(job.runtime_config),
        created_at=job.created_at,
        completed_at=job.completed_at,
    )


def runtime_snapshot():
    return json.dumps(
        {
            key: getattr(settings, key)
            for key in (
                "ocr_languages",
                "render_dpi",
                "ocr_min_confidence",
                "max_image_pixels",
                "max_pages",
            )
        }
    )


def serial_doc(db, doc):
    job = latest_job(db, doc.id)
    return dict(
        id=doc.id,
        filename=doc.filename,
        pages=doc.pages,
        status=doc.status,
        created_at=doc.created_at,
        job=serial_job(job),
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "engineering-drawing-intelligence"}


@app.get("/api/settings")
def runtime_settings():
    return dict(
        engines=available_engines(),
        languages=settings.ocr_languages,
        max_upload_mb=settings.max_upload_mb,
        max_pages=settings.max_pages,
        ocr_min_confidence=settings.ocr_min_confidence,
        environment=settings.environment,
    )


@app.get("/api/session")
def session_status(request: Request):
    actor = (
        session_actor(request.cookies.get(COOKIE, ""))
        if settings.auth_password
        else "local-developer"
    )
    return {
        "authenticated": bool(actor),
        "actor": actor,
        "authentication_required": bool(settings.auth_password),
    }


@app.post("/api/session")
def login(data: LoginIn, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    if throttled(ip):
        raise HTTPException(429, "Too many login attempts; wait one minute")
    if not settings.auth_password or not check_password(data.username, data.password):
        failed_login(ip)
        raise HTTPException(401, "Invalid username or password")
    response.set_cookie(
        COOKIE,
        create_session(),
        httponly=True,
        secure=settings.environment == "production",
        samesite="strict",
        max_age=28800,
        path="/",
    )
    return {"authenticated": True, "actor": settings.auth_username}


@app.delete("/api/session")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"authenticated": False}


@app.post("/api/documents", status_code=202)
@app.post("/api/documents/upload", status_code=202)
async def upload(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg"}:
        raise HTTPException(415, "Use PDF, PNG or JPEG")
    target = Path(settings.upload_dir) / f"{secrets.token_hex(16)}{ext}"
    size = 0
    try:
        with target.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_mb * 1024 * 1024:
                    raise HTTPException(413, "File exceeds configured size limit")
                out.write(chunk)
        if not size:
            raise HTTPException(422, "File is empty")
        try:
            pages = inspect_file(str(target))
        except Exception as exc:
            raise HTTPException(
                422, "Invalid, encrypted, unsupported, or oversized document"
            ) from exc
        document = Document(
            filename=Path((file.filename or "drawing").replace("\\", "/")).name[:255],
            content_type="application/pdf"
            if ext == ".pdf"
            else "image/png"
            if ext == ".png"
            else "image/jpeg",
            pages=pages,
            status="QUEUED",
        )
        db.add(document)
        db.flush()
        job = Job(
            document_id=document.id,
            path=str(target),
            engine=settings.ocr_engine,
            preprocessing="{}",
            runtime_config=runtime_snapshot(),
        )
        db.add(job)
        audit(
            db,
            request,
            "document.upload",
            document.id,
            {"filename": document.filename, "bytes": size},
        )
        db.commit()
        return serial_doc(db, document)
    except Exception:
        db.rollback()
        target.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/documents")
def documents(offset: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    return [
        serial_doc(db, d)
        for d in db.scalars(
            select(Document).order_by(Document.id.desc()).offset(offset).limit(limit)
        )
    ]


@app.get("/api/documents/{document_id}")
def get_document(document_id: int, db: Session = Depends(get_db)):
    return serial_doc(db, document_or_404(db, document_id))


@app.post("/api/documents/{document_id}/process", status_code=202)
def process_document(
    document_id: int,
    options: ProcessIn,
    request: Request,
    db: Session = Depends(get_db),
):
    document = document_or_404(db, document_id)
    # Lock the document on PostgreSQL; SQLite uses an atomic status transition.
    changed = db.execute(
        update(Document)
        .where(
            Document.id == document_id, Document.status.notin_(["QUEUED", "PROCESSING"])
        )
        .values(status="QUEUED")
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "Analysis is already queued or processing")
    previous = latest_job(db, document_id)
    config = options.model_dump()
    selected = config.pop("engine")
    db.add(
        Job(
            document_id=document_id,
            path=previous.path,
            engine=selected,
            preprocessing=json.dumps(config),
            runtime_config=runtime_snapshot(),
        )
    )
    audit(db, request, "document.reprocess", document_id, options.model_dump())
    db.commit()
    db.refresh(document)
    return serial_doc(db, document)


@app.get("/api/documents/{document_id}/results")
def results(document_id: int, job_id: int = 0, db: Session = Depends(get_db)):
    document_or_404(db, document_id)
    job = db.get(Job, job_id) if job_id else latest_job(db, document_id)
    if not job or job.document_id != document_id:
        raise HTTPException(404, "Analysis not found")
    output = []
    for finding, evidence in db.execute(
        select(Finding, Evidence)
        .join(Evidence, Evidence.finding_id == Finding.id)
        .where(Evidence.job_id == job.id)
    ):
        review = db.scalar(
            select(Review)
            .where(Review.finding_id == finding.id)
            .order_by(Review.id.desc())
        )
        output.append(
            dict(
                id=finding.id,
                page=finding.page,
                source_text=finding.source_text,
                normalized_name=finding.normalized_name,
                classification=finding.classification,
                confidence=finding.confidence,
                bbox=json.loads(finding.bbox),
                engine=finding.engine,
                is_material=bool(evidence.is_material),
                match_score=evidence.match_score,
                method=evidence.method,
                explanation=evidence.explanation,
                reference=json.loads(evidence.reference_snapshot),
                alternatives=json.loads(evidence.alternatives),
                review=dict(
                    id=review.id,
                    actor=review.actor,
                    classification=review.classification,
                    reason=review.reason,
                    source=review.source,
                    created_at=review.created_at,
                )
                if review
                else None,
            )
        )
    pages = [
        dict(number=p.number, width=p.width, height=p.height)
        for p in db.scalars(
            select(Page).where(Page.job_id == job.id).order_by(Page.number)
        )
    ]
    return dict(job=serial_job(job), findings=output, pages=pages)


@app.get("/api/documents/{document_id}/history")
def history(document_id: int, db: Session = Depends(get_db)):
    document_or_404(db, document_id)
    return [
        serial_job(j)
        for j in db.scalars(
            select(Job).where(Job.document_id == document_id).order_by(Job.id.desc())
        )
    ]


@app.post("/api/ocr/compare")
def compare(data: CompareIn, db: Session = Depends(get_db)):
    document_or_404(db, data.document_id)
    engines = {}
    for name in ("easyocr", "paddleocr"):
        job = db.scalar(
            select(Job)
            .where(
                Job.document_id == data.document_id,
                Job.engine == name,
                Job.status == "COMPLETE",
            )
            .order_by(Job.id.desc())
        )
        engines[name] = results(data.document_id, job.id, db) if job else None
    return {
        "document_id": data.document_id,
        "engines": engines,
        "instructions": "Run an analysis with each engine, then compare the completed runs. Preprocessing settings are retained with each run.",
    }


@app.get("/api/documents/{document_id}/pages/{number}")
def page_image(
    document_id: int, number: int, job_id: int = 0, db: Session = Depends(get_db)
):
    document_or_404(db, document_id)
    job = db.get(Job, job_id) if job_id else latest_job(db, document_id)
    if not job or job.document_id != document_id:
        raise HTTPException(404, "Analysis not found")
    page = db.scalar(select(Page).where(Page.job_id == job.id, Page.number == number))
    if not page or not Path(page.path).is_file():
        raise HTTPException(404, "Page not rendered yet")
    return FileResponse(page.path, media_type="image/png")


@app.get("/api/materials")
def materials(db: Session = Depends(get_db)):
    return list(db.scalars(select(Material).order_by(Material.standard_name)))


@app.post("/api/materials", status_code=201)
def create_material(data: MaterialIn, request: Request, db: Session = Depends(get_db)):
    if db.scalar(select(Material).where(Material.standard_name == data.standard_name)):
        raise HTTPException(409, "Material name already exists")
    material = Material(**data.model_dump())
    db.add(material)
    db.flush()
    audit(db, request, "material.create", material.id, data.model_dump())
    db.commit()
    return material


@app.put("/api/materials/{material_id}")
def update_material(
    material_id: int, data: MaterialIn, request: Request, db: Session = Depends(get_db)
):
    material = db.get(Material, material_id)
    if not material:
        raise HTTPException(404, "Material not found")
    duplicate = db.scalar(
        select(Material).where(
            Material.standard_name == data.standard_name, Material.id != material_id
        )
    )
    if duplicate:
        raise HTTPException(409, "Material name already exists")
    before = {key: getattr(material, key) for key in data.model_dump()}
    for key, value in data.model_dump().items():
        setattr(material, key, value)
    audit(
        db,
        request,
        "material.update",
        material.id,
        {"before": before, "after": data.model_dump()},
    )
    db.commit()
    return material


def csv_response(rows, name):
    stream = io.StringIO()
    writer = csv.writer(stream)
    for row in rows:
        # Protect spreadsheet exports from formula injection.
        writer.writerow(
            [
                "'" + str(v)
                if str(v).startswith(("=", "+", "-", "@", "\t", "\r"))
                else v
                for v in row
            ]
        )
    return Response(
        stream.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


@app.get("/api/materials/export")
def export_materials(db: Session = Depends(get_db)):
    fields = list(MaterialIn.model_fields)
    return csv_response(
        [fields]
        + [[getattr(m, f) for f in fields] for m in db.scalars(select(Material))],
        "materials.csv",
    )


@app.post("/api/materials/import")
async def import_materials(
    request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    content = await file.read(2 * 1024 * 1024 + 1)
    await file.close()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(413, "CSV limit is 2 MB")
    try:
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
        if len(rows) > 5000:
            raise ValueError("Too many rows")
        items = [MaterialIn.model_validate(row) for row in rows]
        names = [m.standard_name for m in items]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate names")
    except Exception as exc:
        raise HTTPException(422, f"Invalid CSV: {str(exc)[:200]}") from exc
    # Imports are never implicitly trusted, even when their CSV says VERIFIED.
    for item in items:
        material = db.scalar(
            select(Material).where(Material.standard_name == item.standard_name)
        )
        if material:
            continue
        material = Material(
            **{**item.model_dump(), "verification_status": "UNVERIFIED"}
        )
        db.add(material)
    audit(db, request, "material.import", 0, {"rows": len(items)})
    db.commit()
    return {
        "rows": len(items),
        "message": "Imported records require individual verification",
    }


@app.post("/api/reviews", status_code=201)
def create_review(data: ReviewIn, request: Request, db: Session = Depends(get_db)):
    finding = db.get(Finding, data.finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    review = Review(**data.model_dump(), actor=request.state.actor)
    db.add(review)
    audit(db, request, "finding.review", finding.id, data.model_dump())
    db.commit()
    return review


@app.get("/api/audit")
def audit_history(limit: int = 100, db: Session = Depends(get_db)):
    return list(
        db.scalars(
            select(Audit).order_by(Audit.id.desc()).limit(max(1, min(limit, 200)))
        )
    )


@app.get("/api/dashboard/stats")
def dashboard(db: Session = Depends(get_db)):
    docs = list(db.scalars(select(Document)))
    counts = {"ASBESTOS_CONTAINING": 0, "NON_ASBESTOS": 0, "MANUAL_REVIEW": 0}
    confidence = [0, 0, 0, 0, 0]
    categories = {}
    entries = 0
    for doc in docs:
        job = latest_job(db, doc.id)
        if not job or job.status != "COMPLETE":
            continue
        for finding, evidence in db.execute(
            select(Finding, Evidence)
            .join(Evidence, Evidence.finding_id == Finding.id)
            .where(Evidence.job_id == job.id, Evidence.is_material == 1)
        ):
            review = db.scalar(
                select(Review)
                .where(Review.finding_id == finding.id)
                .order_by(Review.id.desc())
            )
            counts[review.classification if review else finding.classification] += 1
            confidence[min(4, int(finding.confidence * 5))] += 1
            category = json.loads(evidence.reference_snapshot).get(
                "category", "Unmatched"
            )
            categories[category] = categories.get(category, 0) + 1
            entries += 1
    return dict(
        documents=len(docs),
        pages=sum(d.pages for d in docs),
        materials=entries,
        classifications=counts,
        categories=categories,
        confidence=confidence,
        processing={
            s: sum(d.status == s for d in docs)
            for s in ("QUEUED", "PROCESSING", "COMPLETE", "FAILED")
        },
    )


@app.get("/api/documents/{document_id}/report")
@app.get("/api/reports/{document_id}")
def report(
    document_id: int,
    format: str = "pdf",
    job_id: int = 0,
    db: Session = Depends(get_db),
):
    doc = document_or_404(db, document_id)
    result = results(document_id, job_id, db)
    if result["job"]["status"] != "COMPLETE":
        raise HTTPException(409, "Report is available after a complete analysis")
    findings = [f for f in result["findings"] if f["is_material"]]
    if format == "csv":
        fields = [
            "page",
            "source_text",
            "normalized_name",
            "classification",
            "confidence",
            "match_score",
            "engine",
            "bbox",
            "explanation",
            "reference",
            "review",
        ]
        return csv_response(
            [fields]
            + [
                [
                    json.dumps(f[k], default=str)
                    if isinstance(f[k], (dict, list))
                    else f[k]
                    for k in fields
                ]
                for f in findings
            ],
            f"analysis-{doc.id}.csv",
        )
    if format != "pdf":
        raise HTTPException(422, "Use pdf or csv")
    from app.services.reporting import pdf_report

    return Response(
        pdf_report(doc, result),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="analysis-{doc.id}.pdf"'
        },
    )
