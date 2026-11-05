"""Durable single-consumer dispatcher; inference runs in a bounded subprocess."""

import logging
import fcntl
import os
import signal
import subprocess
import sys
import time
import threading
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
        if not job or job.status in ("COMPLETE", "FAILED"):
            return
        job.status, job.error, job.completed_at = "FAILED", message, datetime.utcnow()
        db.get(Document, job.document_id).status = "FAILED"
        db.commit()


def heartbeat():
    (Path(settings.upload_dir) / ".worker-heartbeat").touch()


def execute_job(job_id):
    """Keep readiness current and always reap inference on timeout or shutdown."""
    child = subprocess.Popen(
        [sys.executable, "-m", "app.worker", "--job", str(job_id)],
        start_new_session=True,
        env={**os.environ, "ED_DISPATCHER_PID": str(os.getpid())},
    )
    deadline = time.monotonic() + settings.processing_timeout
    timed_out = False
    try:
        while True:
            heartbeat()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                return
            try:
                code = child.wait(timeout=min(1, remaining))
            except subprocess.TimeoutExpired:
                continue
            if code:
                fail(
                    job_id,
                    "OCR process failed. Check worker logs and installed models, then retry.",
                )
            return
    finally:
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
            fail(
                job_id,
                "Processing exceeded configured timeout; retry with fewer pages."
                if timed_out
                else "Worker stopped during processing; retry analysis.",
            )


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
    signal.signal(signal.SIGINT, shutdown)
    # Run one dispatcher per database. Interrupted jobs retain partial evidence and can be retried.
    with SessionLocal() as db:
        for job in db.scalars(select(Job).where(Job.status == "PROCESSING")):
            job.status, job.error = (
                "FAILED",
                "Worker restarted during processing; retry analysis.",
            )
            job.completed_at = datetime.utcnow()
            db.get(Document, job.document_id).status = "FAILED"
        db.commit()
    while True:
        heartbeat()
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
            execute_job(job_id)
        except Exception:
            logger.exception("Could not execute analysis %s", job_id)
            fail(
                job_id,
                "Worker could not execute analysis. Check worker logs, then retry.",
            )


def watch_dispatcher(parent_pid):
    # SIGKILL cannot run the dispatcher's finally block. Stop orphaned inference
    # when its owning dispatcher disappears, including outside Docker.
    while os.getppid() == parent_pid:
        time.sleep(1)
    os._exit(1)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--job":
        if os.environ.get("ED_DISPATCHER_PID"):
            threading.Thread(
                target=watch_dispatcher,
                args=(int(os.environ["ED_DISPATCHER_PID"]),),
                daemon=True,
            ).start()
        try:
            from app.services.processing import process

            process(int(sys.argv[2]))
        except Exception:
            logger.exception("Analysis failed")
            fail(
                int(sys.argv[2]),
                "OCR analysis failed. Check worker logs and installed models, then retry.",
            )
            sys.exit(1)
    else:
        run()
