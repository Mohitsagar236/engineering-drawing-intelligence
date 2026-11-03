import json, os
from pathlib import Path
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import Base, engine, get_db
from app.models.models import Document, Finding
from app.schemas.api import DocumentOut
from app.services.materials import match, seed
from app.services.ocr import pages_for_file, recognize

Base.metadata.create_all(engine)
os.makedirs(settings.upload_dir, exist_ok=True)
app = FastAPI(title="Engineering Drawing Intelligence", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"])

@app.on_event("startup")
def startup():
    from app.db.session import SessionLocal
    db=SessionLocal(); seed(db); db.close()

@app.get("/api/health")
def health(): return {"status":"ok", "service":"engineering-drawing-intelligence"}

@app.post("/api/documents", response_model=DocumentOut)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg"}: raise HTTPException(400, "Supported formats: PDF, PNG, JPG, JPEG")
    target = Path(settings.upload_dir) / f"{os.urandom(8).hex()}{ext}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB limit")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    document = Document(filename=file.filename, content_type=file.content_type or "application/octet-stream", status="PROCESSING")
    db.add(document); db.commit(); db.refresh(document)
    try:
        pages = pages_for_file(str(target)); document.pages = len(pages)
        for index, content in enumerate(pages, 1):
            for text, confidence, bbox in recognize(content, settings.ocr_engine):
                normalized, classification, score = match(db, text)
                db.add(Finding(document_id=document.id, page=index, source_text=text, normalized_name=normalized, classification=classification, confidence=min(confidence, score), bbox=json.dumps(bbox), engine=settings.ocr_engine))
        document.status = "COMPLETE"
    except Exception:
        document.status = "FAILED"
    db.commit(); db.refresh(document)
    return document

@app.get("/api/documents", response_model=list[DocumentOut])
def documents(db: Session = Depends(get_db)): return db.query(Document).order_by(Document.created_at.desc()).all()

@app.get("/api/documents/{document_id}/report")
def report(document_id: int, db: Session = Depends(get_db)):
    doc = db.get(Document, document_id)
    if not doc: raise HTTPException(404, "Document not found")
    lines=["Engineering Drawing Intelligence Report", f"File: {doc.filename}", f"Status: {doc.status}", ""]
    for f in doc.findings: lines.append(f"Page {f.page} | {f.classification} | {f.normalized_name} | source: {f.source_text} | confidence: {f.confidence:.2f}")
    return StreamingResponse(iter(["\n".join(lines)]), media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="report-{doc.id}.txt"'})
