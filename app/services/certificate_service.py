"""Certificate lookup, file locations and ZIP packaging."""
import re
import zipfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import Certificate, CertificateStatus, Job


def certificate_path(job_id: str, certificate_id: str) -> Path:
    """Where a certificate PDF lives: generated/<job_id>/<certificate_id>.pdf"""
    return Path(settings.generated_dir) / job_id / f"{certificate_id}.pdf"


def get_certificate(db: Session, certificate_id: str) -> Certificate | None:
    return db.get(Certificate, certificate_id)


def _safe_filename_part(text: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return cleaned[:50] or fallback


def build_job_zip(job: Job) -> Path | None:
    """Bundle every successful certificate of a job into one ZIP.

    Returns None when the job has no downloadable certificates. The ZIP is
    rebuilt on each call; it is only requested after the job has finished, so
    its contents are stable.
    """
    entries = [
        c
        for c in job.certificates
        if c.status == CertificateStatus.SUCCESS.value
        and c.file_path
        and Path(c.file_path).exists()
    ]
    if not entries:
        return None

    zip_path = Path(settings.generated_dir) / job.id / "certificates.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in entries:
            name = _safe_filename_part(c.recipient_name, c.id[:8])
            # row number prefix keeps names unique and ordered
            zf.write(c.file_path, arcname=f"{c.row_index + 1:04d}_{name}.pdf")
    return zip_path