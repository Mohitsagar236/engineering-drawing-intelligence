import base64
import csv
import io
import json
import logging
import secrets
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import select, text, update, func, or_, exists
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
    Project,
    Tag,
    document_tags,
)
from app.schemas.api import (
    ProcessIn,
    MaterialIn,
    ReviewIn,
    CompareIn,
    LoginIn,
    ProjectIn,
    DocumentUpdate,
)
from app.core.auth import (
    COOKIE,
    create_session,
    session_actor,
    check_password,
    throttled,
    failed_login,
    revoke_session,
)
from app.services.materials import seed, MATCHING_RULES_VERSION
from app.services.ocr import inspect_file, available_engines
from app.services.extraction import extract

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

    def finish(response):
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

    request.state.actor = "local-developer"
    login_request = request.url.path == "/api/session" and request.method == "POST"
    ip = request.client.host if request.client else "unknown"
    if login_request and throttled(ip):
        return finish(
            JSONResponse(
                {"detail": "Too many login attempts; wait one minute"},
                status_code=429,
                headers={"Retry-After": "60"},
            )
        )
    if settings.auth_password and request.url.path not in (
        "/api/health",
        "/api/ready",
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
            if request.headers.get("Authorization"):
                ip = request.client.host if request.client else "unknown"
                if throttled(ip):
                    return finish(
                        JSONResponse(
                            {"detail": "Too many login attempts; wait one minute"},
                            status_code=429,
                            headers={"Retry-After": "60"},
                        )
                    )
                failed_login(ip)
            return finish(
                Response(
                    status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="Drawing Intelligence"'},
                )
            )
        request.state.actor = actor or user
    if request.method in ("POST", "PUT", "DELETE") and request.headers.get("origin"):
        if request.headers["origin"] not in settings.cors_origin_list:
            return finish(
                JSONResponse({"detail": "Origin is not permitted"}, status_code=403)
            )
    response = await call_next(request)
    if login_request and response.status_code in (400, 401, 413, 422):
        failed_login(ip)
    return finish(response)


@app.exception_handler(RequestValidationError)
async def invalid_request(request: Request, exception: RequestValidationError):
    # Do not reflect credentials or large rejected inputs in validation responses.
    return JSONResponse(
        {
            "detail": [
                {key: error[key] for key in ("type", "loc", "msg")}
                for error in exception.errors()
            ]
        },
        status_code=422,
    )


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
            "matching_rules_version": MATCHING_RULES_VERSION,
            **{
                key: getattr(settings, key)
                for key in (
                    "ocr_languages",
                    "render_dpi",
                    "ocr_min_confidence",
                    "max_image_pixels",
                    "max_pages",
                )
            },
        }
    )


def serial_doc(db, doc, job=None):
    job = job or latest_job(db, doc.id)
    return dict(
        id=doc.id,
        filename=doc.filename,
        pages=doc.pages,
        status=doc.status,
        created_at=doc.created_at,
        project_id=doc.project_id,
        tags=sorted(tag.name for tag in doc.tags),
        job=serial_job(job),
    )


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "service": "engineering-drawing-intelligence"}


@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    """Readiness includes the dispatcher, unlike the API liveness endpoint."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Readiness database check failed")
        return JSONResponse(
            {"status": "unavailable", "database": False}, status_code=503
        )
    try:
        heartbeat = Path(settings.upload_dir) / ".worker-heartbeat"
        worker = 0 <= time.time() - heartbeat.stat().st_mtime < 15
    except OSError:
        worker = False
    return JSONResponse(
        {
            "status": "ready" if worker else "unavailable",
            "database": True,
            "worker": worker,
        },
        status_code=200 if worker else 503,
    )


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
    if not settings.auth_password or not check_password(data.username, data.password):
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
def logout(request: Request, response: Response):
    revoke_session(request.cookies.get(COOKIE, ""))
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


def like_pattern(value):
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@app.get("/api/documents")
def documents(
    response: Response,
    offset: int = 0,
    limit: int = 100,
    q: str = "",
    status: str = "",
    project_id: int = 0,
    tag: str = "",
    db: Session = Depends(get_db),
):
    if offset < 0 or not 1 <= limit <= 200:
        raise HTTPException(422, "Invalid pagination")
    latest = select(func.max(Job.id).label("id")).group_by(Job.document_id).subquery()
    query = select(Document, Job).outerjoin(
        Job, (Job.document_id == Document.id) & Job.id.in_(select(latest.c.id))
    )
    q = q.strip()[:200]
    if q:
        pattern = like_pattern(q)
        query = query.where(
            or_(
                Document.filename.ilike(pattern, escape="\\"),
                exists().where(
                    Finding.document_id == Document.id,
                    Finding.source_text.ilike(pattern, escape="\\"),
                ),
                exists().where(
                    document_tags.c.document_id == Document.id,
                    document_tags.c.tag_id == Tag.id,
                    Tag.name.ilike(pattern, escape="\\"),
                ),
            )
        )
    if status:
        query = query.where(Document.status == status.upper())
    if project_id == -1:
        query = query.where(Document.project_id.is_(None))
    elif project_id:
        query = query.where(Document.project_id == project_id)
    if tag.strip():
        query = query.where(
            exists().where(
                document_tags.c.document_id == Document.id,
                document_tags.c.tag_id == Tag.id,
                Tag.name == " ".join(tag.lower().split()),
            )
        )
    response.headers["X-Total-Count"] = str(
        db.scalar(
            select(func.count()).select_from(
                query.with_only_columns(Document.id).subquery()
            )
        )
    )
    return [
        serial_doc(db, document, job)
        for document, job in db.execute(
            query.order_by(Document.id.desc()).offset(offset).limit(limit)
        )
    ]


@app.patch("/api/documents/{document_id}")
def update_document(
    document_id: int,
    data: DocumentUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    document = document_or_404(db, document_id)
    changes = {}
    if "project_id" in data.model_fields_set:
        if data.project_id is not None and not db.get(Project, data.project_id):
            raise HTTPException(404, "Project not found")
        document.project_id = data.project_id
        changes["project_id"] = data.project_id
    if data.tags is not None:
        existing = {
            t.name: t for t in db.scalars(select(Tag).where(Tag.name.in_(data.tags)))
        }
        document.tags = [existing.get(name) or Tag(name=name) for name in data.tags]
        changes["tags"] = data.tags
    if changes:
        audit(db, request, "document.update", document_id, changes)
    db.commit()
    return serial_doc(db, document)


@app.get("/api/tags")
def tags(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(document_tags.c.tag_id, func.count()).group_by(
                document_tags.c.tag_id
            )
        ).all()
    )
    return [
        dict(id=t.id, name=t.name, documents=counts.get(t.id, 0))
        for t in db.scalars(select(Tag).order_by(Tag.name))
        if counts.get(t.id)
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
    if not previous or not Path(previous.path).is_file():
        db.rollback()
        raise HTTPException(
            409, "Original upload is unavailable; upload the drawing again"
        )
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
    latest_reviews = select(func.max(Review.id)).group_by(Review.finding_id)
    for finding, evidence, review in db.execute(
        select(Finding, Evidence, Review)
        .join(Evidence, Evidence.finding_id == Finding.id)
        .outerjoin(
            Review, (Review.finding_id == Finding.id) & Review.id.in_(latest_reviews)
        )
        .where(Evidence.job_id == job.id)
        .order_by(Finding.page, Finding.id)
    ):
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
                if str(v).lstrip(" \t\r\n").startswith(("=", "+", "-", "@"))
                or str(v).startswith(("\t", "\r", "\n"))
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
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
        fields = reader.fieldnames
        if (
            not fields
            or "standard_name" not in fields
            or len(set(fields)) != len(fields)
        ):
            raise ValueError(
                "CSV requires unique column headers including standard_name"
            )
        if set(fields) - set(MaterialIn.model_fields):
            raise ValueError("CSV contains unsupported columns")
        rows = list(reader)
        if not rows:
            raise ValueError("CSV contains no material records")
        if len(rows) > 5000:
            raise ValueError("Too many rows")
        items = [MaterialIn.model_validate(row) for row in rows]
        names = [m.standard_name for m in items]
        if len(set(names)) != len(names):
            raise ValueError("Duplicate names")
    except Exception as exc:
        raise HTTPException(422, f"Invalid CSV: {str(exc)[:200]}") from exc
    # Imports are never implicitly trusted, even when their CSV says VERIFIED.
    imported = 0
    existing = set(db.scalars(select(Material.standard_name)))
    for item in items:
        if item.standard_name in existing:
            continue
        material = Material(
            **{**item.model_dump(), "verification_status": "UNVERIFIED"}
        )
        db.add(material)
        imported += 1
    audit(
        db,
        request,
        "material.import",
        0,
        {"rows": len(items), "imported": imported, "skipped": len(items) - imported},
    )
    db.commit()
    return {
        "rows": len(items),
        "imported": imported,
        "skipped": len(items) - imported,
        "message": "Imported records require individual verification",
    }


@app.post("/api/reviews", status_code=201)
def create_review(data: ReviewIn, request: Request, db: Session = Depends(get_db)):
    finding = db.get(Finding, data.finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    evidence = db.scalar(select(Evidence).where(Evidence.finding_id == finding.id))
    if not evidence or db.get(Job, evidence.job_id).status != "COMPLETE":
        raise HTTPException(409, "Review is available only for a completed analysis")
    review = Review(**data.model_dump(), actor=request.state.actor)
    db.add(review)
    audit(db, request, "finding.review", finding.id, data.model_dump())
    db.commit()
    return review


@app.get("/api/audit")
def audit_history(
    response: Response,
    limit: int = 100,
    offset: int = 0,
    action: str = "",
    actor: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    if offset < 0:
        raise HTTPException(422, "Invalid pagination")
    query = select(Audit)
    if action.strip():
        query = query.where(Audit.action == action.strip())
    if actor.strip():
        query = query.where(Audit.actor == actor.strip())
    if q.strip():
        pattern = like_pattern(q.strip()[:200])
        query = query.where(
            or_(
                Audit.payload.ilike(pattern, escape="\\"),
                Audit.action.ilike(pattern, escape="\\"),
            )
        )
    response.headers["X-Total-Count"] = str(
        db.scalar(select(func.count()).select_from(query.subquery()))
    )
    return list(
        db.scalars(
            query.order_by(Audit.id.desc())
            .offset(offset)
            .limit(max(1, min(limit, 200)))
        )
    )


@app.get("/api/audit/filters")
def audit_filters(db: Session = Depends(get_db)):
    return dict(
        actions=list(
            db.scalars(select(Audit.action).distinct().order_by(Audit.action))
        ),
        actors=list(db.scalars(select(Audit.actor).distinct().order_by(Audit.actor))),
    )


def material_stats(db, project_id=0):
    counts = {"ASBESTOS_CONTAINING": 0, "NON_ASBESTOS": 0, "MANUAL_REVIEW": 0}
    confidence = [0, 0, 0, 0, 0]
    categories = {}
    per_document = {}
    entries = 0
    latest_jobs = select(func.max(Job.id)).group_by(Job.document_id)
    latest_reviews = select(func.max(Review.id)).group_by(Review.finding_id)
    query = (
        select(Finding, Evidence, Review)
        .join(Evidence, Evidence.finding_id == Finding.id)
        .join(Job, Job.id == Evidence.job_id)
        .outerjoin(
            Review, (Review.finding_id == Finding.id) & Review.id.in_(latest_reviews)
        )
        .where(
            Job.id.in_(latest_jobs), Job.status == "COMPLETE", Evidence.is_material == 1
        )
    )
    if project_id:
        query = query.join(Document, Document.id == Job.document_id).where(
            Document.project_id == project_id
        )
    for finding, evidence, review in db.execute(query):
        result = review.classification if review else finding.classification
        counts[result] += 1
        confidence[min(4, max(0, int(finding.confidence * 5)))] += 1
        category = json.loads(evidence.reference_snapshot).get("category", "Unmatched")
        categories[category] = categories.get(category, 0) + 1
        bucket = per_document.setdefault(
            finding.document_id,
            {"ASBESTOS_CONTAINING": 0, "NON_ASBESTOS": 0, "MANUAL_REVIEW": 0},
        )
        bucket[result] += 1
        entries += 1
    return counts, confidence, categories, per_document, entries


@app.get("/api/dashboard/stats")
def dashboard(db: Session = Depends(get_db)):
    statuses = dict(
        db.execute(
            select(Document.status, func.count()).group_by(Document.status)
        ).all()
    )
    page_count = db.scalar(select(func.coalesce(func.sum(Document.pages), 0)))
    counts, confidence, categories, _, entries = material_stats(db)
    return dict(
        documents=sum(statuses.values()),
        pages=page_count,
        materials=entries,
        classifications=counts,
        categories=categories,
        confidence=confidence,
        processing={
            s: statuses.get(s, 0)
            for s in ("QUEUED", "PROCESSING", "COMPLETE", "FAILED")
        },
    )


def project_or_404(db, project_id):
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@app.get("/api/projects")
def projects(db: Session = Depends(get_db)):
    counts = dict(
        db.execute(
            select(Document.project_id, func.count())
            .where(Document.project_id.is_not(None))
            .group_by(Document.project_id)
        ).all()
    )
    return [
        dict(
            id=p.id,
            name=p.name,
            description=p.description,
            created_at=p.created_at,
            documents=counts.get(p.id, 0),
        )
        for p in db.scalars(select(Project).order_by(Project.name))
    ]


@app.post("/api/projects", status_code=201)
def create_project(data: ProjectIn, request: Request, db: Session = Depends(get_db)):
    project = Project(**data.model_dump())
    db.add(project)
    db.flush()
    audit(db, request, "project.create", project.id, data.model_dump())
    db.commit()
    return dict(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
        documents=0,
    )


@app.put("/api/projects/{project_id}")
def update_project(
    project_id: int, data: ProjectIn, request: Request, db: Session = Depends(get_db)
):
    project = project_or_404(db, project_id)
    for key, value in data.model_dump().items():
        setattr(project, key, value)
    audit(db, request, "project.update", project.id, data.model_dump())
    db.commit()
    return dict(
        id=project.id,
        name=project.name,
        description=project.description,
        created_at=project.created_at,
    )


@app.delete("/api/projects/{project_id}", status_code=204)
def delete_project(project_id: int, request: Request, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    # Documents are kept; they simply become unassigned.
    db.execute(
        update(Document)
        .where(Document.project_id == project_id)
        .values(project_id=None)
    )
    audit(db, request, "project.delete", project.id, {"name": project.name})
    db.delete(project)
    db.commit()
    return Response(status_code=204)


@app.get("/api/projects/{project_id}/summary")
def project_summary(project_id: int, db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    counts, confidence, categories, per_document, entries = material_stats(
        db, project_id
    )
    rows = []
    statuses = {}
    for document, job in db.execute(
        select(Document, Job)
        .outerjoin(
            Job,
            (Job.document_id == Document.id)
            & Job.id.in_(select(func.max(Job.id)).group_by(Job.document_id)),
        )
        .where(Document.project_id == project_id)
        .order_by(Document.id.desc())
    ):
        statuses[document.status] = statuses.get(document.status, 0) + 1
        rows.append(
            dict(
                **serial_doc(db, document, job),
                classifications=per_document.get(
                    document.id,
                    {"ASBESTOS_CONTAINING": 0, "NON_ASBESTOS": 0, "MANUAL_REVIEW": 0},
                ),
            )
        )
    return dict(
        project=dict(id=project.id, name=project.name, description=project.description),
        documents=len(rows),
        pages=sum(r["pages"] for r in rows),
        materials=entries,
        classifications=counts,
        categories=categories,
        confidence=confidence,
        processing={
            s: statuses.get(s, 0)
            for s in ("QUEUED", "PROCESSING", "COMPLETE", "FAILED")
        },
        items=rows,
    )


@app.get("/api/documents/{document_id}/extraction")
def extraction(
    document_id: int,
    job_id: int = 0,
    format: str = "json",
    db: Session = Depends(get_db),
):
    if format not in ("json", "csv"):
        raise HTTPException(422, "Use json or csv")
    result = results(document_id, job_id, db)
    if result["job"]["status"] != "COMPLETE":
        raise HTTPException(409, "Extraction is available after a complete analysis")
    data = extract(result["findings"], result["pages"])
    if format == "csv":
        rows = [["type", "page", "field", "value", "unit", "tolerance", "confidence"]]
        for e in data["title_block"]:
            rows.append(
                [
                    "title_block",
                    e["source"]["page"],
                    e["field"],
                    e["value"],
                    "",
                    "",
                    e["source"]["confidence"],
                ]
            )
        for d in data["dimensions"]:
            rows.append(
                [
                    "dimension",
                    d["source"]["page"],
                    d["kind"],
                    d["value"],
                    d["unit"],
                    d["tolerance"],
                    d["source"]["confidence"],
                ]
            )
        for table in data["bom"]:
            for number, row in enumerate(table["rows"], 1):
                for field, value in row["cells"].items():
                    rows.append(
                        [f"bom_row_{number}", table["page"], field, value, "", "", ""]
                    )
        return csv_response(rows, f"extraction-{document_id}.csv")
    return dict(
        job=result["job"],
        method="heuristic-v1",
        note="Values are parsed from OCR text and positions; verify against the drawing.",
        **data,
    )


REPORT_FIELDS = [
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


def finding_rows(findings):
    return [
        [
            json.dumps(f[k], default=str) if isinstance(f[k], (dict, list)) else f[k]
            for k in REPORT_FIELDS
        ]
        for f in findings
        if f["is_material"]
    ]


def batch_documents(db, ids):
    if not ids or len(ids) > 50:
        raise HTTPException(422, "Select between 1 and 50 documents")
    ready, skipped = [], []
    for document_id in ids:
        doc = document_or_404(db, document_id)
        result = results(document_id, 0, db)
        (ready if result["job"]["status"] == "COMPLETE" else skipped).append(
            (doc, result)
        )
    if not ready:
        raise HTTPException(409, "No selected document has a complete analysis")
    return ready, [doc.id for doc, _ in skipped]


def parse_ids(ids):
    try:
        values = [int(x) for x in ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "ids must be comma-separated integers")
    return list(dict.fromkeys(values))


def batch_response(db, ids, format, name):
    if format not in ("csv", "pdf"):
        raise HTTPException(422, "Use pdf or csv")
    ready, skipped = batch_documents(db, ids)
    headers = {"X-Skipped-Documents": ",".join(map(str, skipped))}
    if format == "csv":
        rows = [["document_id", "filename", *REPORT_FIELDS]]
        for doc, result in ready:
            rows += [
                [doc.id, doc.filename, *row] for row in finding_rows(result["findings"])
            ]
        response = csv_response(rows, f"{name}.csv")
        response.headers.update(headers)
        return response
    from app.services.reporting import pdf_report

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for doc, result in ready:
            bundle.writestr(f"analysis-{doc.id}.pdf", pdf_report(doc, result))
    return Response(
        archive.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{name}.zip"',
            **headers,
        },
    )


@app.get("/api/reports/batch")
def batch_report(ids: str, format: str = "csv", db: Session = Depends(get_db)):
    return batch_response(db, parse_ids(ids), format, "analysis-batch")


@app.get("/api/projects/{project_id}/report")
def project_report(project_id: int, format: str = "pdf", db: Session = Depends(get_db)):
    project = project_or_404(db, project_id)
    if format not in ("csv", "pdf", "zip"):
        raise HTTPException(422, "Use pdf, csv or zip")
    if format == "pdf":
        from app.services.reporting import project_pdf

        return Response(
            project_pdf(project, project_summary(project_id, db)),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="project-{project.id}.pdf"'
            },
        )
    ids = list(db.scalars(select(Document.id).where(Document.project_id == project_id)))
    return batch_response(
        db, ids, "pdf" if format == "zip" else "csv", f"project-{project.id}"
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
    if format == "csv":
        return csv_response(
            [REPORT_FIELDS] + finding_rows(result["findings"]),
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
