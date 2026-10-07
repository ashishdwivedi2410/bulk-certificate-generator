"""Background worker: generates every pending certificate of a job.

Failure isolation: each certificate is generated inside its own try/except, so
one bad recipient is recorded as FAILED and the loop carries on. Counters are
committed after every certificate so GET /jobs/{id} shows live progress.

Runs via FastAPI BackgroundTasks (in-process, after the 202 response is sent).
"""
import logging
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.db.models import Certificate, CertificateStatus, Job
from app.services import certificate_service, generator_service, job_service

logger = logging.getLogger(__name__)


def process_job(job_id: str, session_factory: Callable[[], Session] | None = None) -> None:
    # The worker must open its OWN session: the request's session is closed
    # by the time a background task runs.
    db = (session_factory or SessionLocal)()
    try:
        job = job_service.get_job(db, job_id)
        if job is None:
            logger.error("process_job: job %s not found", job_id)
            return

        job_service.mark_processing(db, job)

        pending = db.execute(
            select(Certificate)
            .where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING.value,
            )
            .order_by(Certificate.row_index)
        ).scalars().all()

        for cert in pending:
            _process_one(db, job, cert)

        job_service.finalize_job(job)
        db.commit()
    except Exception:
        # Unexpected infrastructure error (e.g. DB): don't leave the job stuck.
        logger.exception("process_job crashed for job %s", job_id)
        db.rollback()
        _abort_job(db, job_id)
    finally:
        db.close()


def _process_one(db: Session, job: Job, cert: Certificate) -> None:
    try:
        path = certificate_service.certificate_path(job.id, cert.id)
        generator_service.generate_certificate(
            recipient_name=cert.recipient_name,
            course_name=job.course_name,
            issued_by=job.issued_by,
            issue_date=job.issue_date,
            output_path=path,
        )
        cert.status = CertificateStatus.SUCCESS.value
        cert.file_path = str(path)
        job.succeeded += 1
    except Exception as exc:  # isolate ANY per-certificate failure
        logger.warning("Certificate %s failed: %s", cert.id, exc)
        cert.status = CertificateStatus.FAILED.value
        cert.error_message = str(exc)[:1000]
        job.failed += 1
    db.commit()


def _abort_job(db: Session, job_id: str) -> None:
    """Best effort: mark unfinished certificates failed and close the job."""
    try:
        job = job_service.get_job(db, job_id)
        if job is None:
            return
        for cert in job.certificates:
            if cert.status in (CertificateStatus.PENDING.value,):
                cert.status = CertificateStatus.FAILED.value
                cert.error_message = "Job aborted due to an internal error"
                job.failed += 1
        job_service.finalize_job(job)
        db.commit()
    except Exception:
        logger.exception("Could not abort job %s cleanly", job_id)
        db.rollback()