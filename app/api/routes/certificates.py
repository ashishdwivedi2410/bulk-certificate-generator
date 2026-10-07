"""Endpoints for retrieving individual generated certificates."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.services import certificate_service

router = APIRouter(prefix="/certificates", tags=["certificates"])


@router.get("/{certificate_id}/download")
def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
    """Download one generated certificate as a PDF."""
    cert = certificate_service.get_certificate(db, certificate_id)
    if cert is None:
        raise HTTPException(status_code=404, detail="Certificate not found")
    if cert.status != "success":
        raise HTTPException(
            status_code=409,
            detail=f"Certificate is not available (status: {cert.status})",
        )
    if not cert.file_path or not Path(cert.file_path).exists():
        raise HTTPException(status_code=404, detail="Certificate file missing")
    return FileResponse(
        cert.file_path,
        media_type="application/pdf",
        filename=f"certificate_{cert.id}.pdf",
    )