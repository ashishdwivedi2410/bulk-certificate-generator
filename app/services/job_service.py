"""Job lifecycle: create (with per-row validation), read, mark processing, finalize."""
from datetime import datetime, timezone

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Certificate, CertificateStatus, Job, JobStatus
from app.schemas.certificate import RecipientInput
from app.schemas.job import JobCreateRequest


def _format_validation_error(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in err['loc']) or 'row'}: {err['msg']}"
        for err in exc.errors()
    )


def _best_effort_str(value, max_len: int) -> str | None:
    """Keep whatever the client sent for an invalid row, so it can be identified."""
    if value is None:
        return None
    return str(value)[:max_len]


def status_from_counts(total: int, succeeded: int, failed: int) -> JobStatus:
    if failed == 0 and succeeded == total:
        return JobStatus.COMPLETED
    if succeeded == 0:
        return JobStatus.FAILED
    return JobStatus.COMPLETED_WITH_ERRORS


def create_job(db: Session, payload: JobCreateRequest) -> Job:
    """Store the job and one Certificate row per recipient.

    Each recipient is validated on its own. Invalid rows are saved as FAILED
    with an error message (and never reach the worker); valid rows are PENDING.
    """
    job = Job(
        course_name=payload.course_name.strip(),
        issued_by=payload.issued_by.strip(),
        issue_date=payload.issue_date,
        total=len(payload.recipients),
        # Set explicitly: column defaults only apply at INSERT time, and we
        # increment these before the job is flushed.
        succeeded=0,
        failed=0,
    )

    for index, raw in enumerate(payload.recipients):
        try:
            recipient = RecipientInput.model_validate(raw)
        except ValidationError as exc:
            job.certificates.append(
                Certificate(
                    row_index=index,
                    recipient_name=_best_effort_str(raw.get("name"), 200),
                    recipient_email=_best_effort_str(raw.get("email"), 320),
                    status=CertificateStatus.FAILED.value,
                    error_message=_format_validation_error(exc),
                )
            )
            job.failed += 1
        else:
            job.certificates.append(
                Certificate(
                    row_index=index,
                    recipient_name=recipient.name,
                    recipient_email=str(recipient.email),
                    status=CertificateStatus.PENDING.value,
                )
            )

    # Nothing left for the worker (every row invalid): the job is already done.
    if job.failed == job.total:
        finalize_job(job)

    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str) -> Job | None:
    stmt = select(Job).where(Job.id == job_id).options(selectinload(Job.certificates))
    return db.execute(stmt).scalar_one_or_none()


def mark_processing(db: Session, job: Job) -> None:
    job.status = JobStatus.PROCESSING.value
    db.commit()


def finalize_job(job: Job) -> None:
    """Set the final status from the counters. Caller commits."""
    job.status = status_from_counts(job.total, job.succeeded, job.failed).value
    job.completed_at = datetime.now(timezone.utc)