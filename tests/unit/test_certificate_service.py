import zipfile

from app.core.config import settings
from app.db.models import CertificateStatus
from app.schemas.job import JobCreateRequest
from app.services import certificate_service, job_service


def make_job_with_files(db, names, write_files=True):
    """Create a job whose certificates are already 'successful' with fake files."""
    req = JobCreateRequest(
        course_name="Course",
        issued_by="Acme",
        issue_date="2026-10-01",
        recipients=[{"name": n, "email": f"u{i}@example.com"} for i, n in enumerate(names)],
    )
    job = job_service.create_job(db, req)
    for cert in job.certificates:
        path = certificate_service.certificate_path(job.id, cert.id)
        if write_files:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"%PDF-fake")
        cert.status = CertificateStatus.SUCCESS.value
        cert.file_path = str(path)
    db.commit()
    return job


def test_certificate_path_layout():
    path = certificate_service.certificate_path("job1", "cert1")
    assert path == settings.generated_dir / "job1" / "cert1.pdf"


def test_get_certificate_found_and_missing(db):
    job = make_job_with_files(db, ["Asha"])
    cert = job.certificates[0]
    assert certificate_service.get_certificate(db, cert.id).id == cert.id
    assert certificate_service.get_certificate(db, "nope") is None


def test_build_job_zip_contains_successful_certificates(db):
    job = make_job_with_files(db, ["Asha Verma", "Ravi Kumar"])
    zip_path = certificate_service.build_job_zip(job)

    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        assert zf.namelist() == ["0001_Asha_Verma.pdf", "0002_Ravi_Kumar.pdf"]
        assert zf.read("0001_Asha_Verma.pdf") == b"%PDF-fake"


def test_build_job_zip_skips_failed_certificates(db):
    job = make_job_with_files(db, ["Asha", "Ravi"])
    job.certificates[1].status = CertificateStatus.FAILED.value
    db.commit()

    with zipfile.ZipFile(certificate_service.build_job_zip(job)) as zf:
        assert zf.namelist() == ["0001_Asha.pdf"]


def test_build_job_zip_skips_files_missing_on_disk(db):
    job = make_job_with_files(db, ["Asha", "Ravi"])
    certificate_service.certificate_path(job.id, job.certificates[0].id).unlink()

    with zipfile.ZipFile(certificate_service.build_job_zip(job)) as zf:
        assert zf.namelist() == ["0002_Ravi.pdf"]


def test_build_job_zip_returns_none_when_nothing_to_zip(db):
    job = make_job_with_files(db, ["Asha"], write_files=False)
    assert certificate_service.build_job_zip(job) is None


def test_zip_filenames_are_sanitized(db):
    job = make_job_with_files(db, ["O'Brien / Jr.", "../../etc/passwd"])
    with zipfile.ZipFile(certificate_service.build_job_zip(job)) as zf:
        names = zf.namelist()
    assert names == ["0001_O_Brien_Jr.pdf", "0002_etc_passwd.pdf"]
    assert all("/" not in n and ".." not in n for n in names)


def test_zip_filename_falls_back_to_id_for_non_latin_names(db):
    job = make_job_with_files(db, ["राहुल"])
    cert = job.certificates[0]
    with zipfile.ZipFile(certificate_service.build_job_zip(job)) as zf:
        assert zf.namelist() == [f"0001_{cert.id[:8]}.pdf"]


def test_build_job_zip_can_be_called_twice(db):
    job = make_job_with_files(db, ["Asha"])
    first = certificate_service.build_job_zip(job)
    second = certificate_service.build_job_zip(job)
    assert first == second and second.exists()