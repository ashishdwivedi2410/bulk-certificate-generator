"""Endpoints for creating and tracking bulk certificate jobs."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.schemas.job import JobCreateRequest, JobCreateResponse, JobStatusResponse
from app.services import certificate_service, job_service
from app.workers import process_job

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post(
    "",
    response_model=JobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_job(
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Accept a bulk request, store it, and generate in the background.

    Returns 202 immediately with a job id; the client polls GET /jobs/{id}.
    """
    job = job_service.create_job(db, payload)
    background_tasks.add_task(process_job, job.id)
    return job


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Return progress counts and per-recipient results for a job."""
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/{job_id}/download")
def download_job_certificates(job_id: str, db: Session = Depends(get_db)):
    """Download all successfully generated certificates of a job as a ZIP."""
    job = job_service.get_job(db, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("pending", "processing"):
        raise HTTPException(status_code=409, detail="Job is still running")

    zip_path = certificate_service.build_job_zip(job)
    if zip_path is None:
        raise HTTPException(status_code=404, detail="No certificates were generated")
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=f"certificates_{job.id}.zip",
    )