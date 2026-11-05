import json
import math
from importlib.metadata import version, PackageNotFoundError
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, update, func
from app.db.session import SessionLocal
from app.models.models import Document, Job, Page, Finding, Evidence, Material
from app.services.ocr import iter_pages, inspect_file, recognize_image
from app.services.materials import analyze, is_material
from app.core.config import settings


def process(job_id):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        for key, value in json.loads(job.runtime_config).items():
            if key in type(settings).model_fields:
                setattr(settings, key, value)
        runtime = json.loads(job.runtime_config)
        versions = {}
        for package in (
            "easyocr",
            "paddleocr",
            "paddlepaddle",
            "torch",
            "PyMuPDF",
            "opencv-python-headless",
        ):
            try:
                versions[package] = version(package)
            except PackageNotFoundError:
                continue
        job.runtime_config = json.dumps({**runtime, "package_versions": versions})
        document = db.get(Document, job.document_id)
        # Use one consistent catalog snapshot throughout an analysis, without a
        # full catalog query for every recognized annotation.
        catalog = db.query(Material).all()
        inspect_file(job.path)
        directory = Path(settings.upload_dir) / "pages" / str(job.id)
        directory.mkdir(parents=True, exist_ok=True)
        for number, image in enumerate(iter_pages(job.path), 1):
            if db.scalar(select(Job.status).where(Job.id == job.id)) not in (
                "QUEUED",
                "PROCESSING",
            ):
                raise RuntimeError("Analysis is no longer active")
            path = directory / f"{number}.png"
            image.save(path)
            db.add(
                Page(
                    job_id=job.id,
                    number=number,
                    width=image.width,
                    height=image.height,
                    path=str(path),
                )
            )
            db.commit()
            for text, confidence, box, engine in recognize_image(
                image, job.engine, json.loads(job.preprocessing)
            ):
                if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                    raise ValueError("OCR returned an invalid confidence score")
                result = analyze(db, text, confidence, records=catalog)
                finding = Finding(
                    document_id=document.id,
                    page=number,
                    source_text=text,
                    normalized_name=result["name"][:255],
                    classification=result["classification"],
                    confidence=confidence,
                    bbox=json.dumps(box),
                    engine=engine,
                )
                db.add(finding)
                db.flush()
                db.add(
                    Evidence(
                        finding_id=finding.id,
                        job_id=job.id,
                        material_id=result["material_id"],
                        is_material=int(is_material(text, result)),
                        match_score=result["score"],
                        method=result["method"],
                        explanation=result["explanation"],
                        reference_snapshot=json.dumps(result["snapshot"]),
                        alternatives=json.dumps(result["alternatives"]),
                    )
                )
            db.commit()
        changed = db.execute(
            update(Job)
            .where(Job.id == job.id, Job.status.in_(["QUEUED", "PROCESSING"]))
            .values(status="COMPLETE", completed_at=datetime.utcnow())
        )
        if changed.rowcount != 1:
            db.rollback()
            raise RuntimeError("Analysis was interrupted; completion was not published")
        latest = (
            select(func.max(Job.id))
            .where(Job.document_id == document.id)
            .scalar_subquery()
        )
        db.execute(
            update(Document)
            .where(Document.id == document.id, latest == job.id)
            .values(status="COMPLETE")
        )
        db.commit()
