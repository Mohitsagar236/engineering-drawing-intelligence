"""Durable single-consumer dispatcher; inference runs in a bounded subprocess."""

import logging
import fcntl
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from sqlalchemy import select, update
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.models import Job, Document

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def fail(job_id, message):
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        if job.status == "FAILED" and job.error:
            return
        job.status, job.error, job.completed_at = "FAILED", message, datetime.utcnow()
        db.get(Document, job.document_id).status = "FAILED"
        db.commit()


def run():
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    lock = open(Path(settings.upload_dir) / ".worker.lock", "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError(
            "A dispatcher already owns this upload directory; run one worker"
        )

    def shutdown(signum, frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, shutdown)
    # Run one dispatcher per database. Interrupted jobs retain partial evidence and can be retried.
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "PROCESSING")):
            job.status, job.error = (
                "FAILED",
                "Worker restarted during processing; retry analysis.",
            )
            db.get(Document, job.document_id).status = "FAILED"
        db.commit()
    while True:
        with SessionLocal() as db:
            job = db.scalar(select(Job).where(Job.status == "QUEUED").order_by(Job.id))
            if job is None:
                job_id = None
            else:
                job_id = job.id
                changed = db.execute(
                    update(Job)
                    .where(Job.id == job_id, Job.status == "QUEUED")
                    .values(status="PROCESSING", started_at=datetime.utcnow())
                )
                if changed.rowcount != 1:
                    continue
                db.get(Document, job.document_id).status = "PROCESSING"
                db.commit()
        if job_id is None:
            time.sleep(1)
            continue
        try:
            outcome = subprocess.run(
                [sys.executable, "-m", "app.worker", "--job", str(job_id)],
                timeout=settings.processing_timeout,
                check=False,
            )
            if outcome.returncode:
                fail(
                    job_id,
                    "OCR process failed. Check worker logs and installed models, then retry.",
                )
        except subprocess.TimeoutExpired:
            fail(
                job_id,
                "Processing exceeded configured timeout; retry with fewer pages.",
            )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        try:
            from app.services.processing import process

            process(int(sys.argv[2]))
        except Exception as exc:
            logger.exception("Analysis failed")
            fail(int(sys.argv[2]), f"{type(exc).__name__}: {str(exc)[:500]}")
            sys.exit(1)
    else:
        run()
