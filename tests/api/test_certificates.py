import io
import zipfile
from datetime import date

from app.db.models import Certificate, Job


def test_download_single_certificate(client, submit_job):
    _, status = submit_job()
    cert = status["certificates"][0]

    response = client.get(cert["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-")
    assert f"certificate_{cert['id']}.pdf" in response.headers["content-disposition"]


def test_each_certificate_downloads_different_content(client, submit_job):
    _, status = submit_job()
    a, b = (client.get(c["download_url"]).content for c in status["certificates"])
    assert a != b


def test_download_unknown_certificate_returns_404(client):
    assert client.get("/certificates/nope/download").status_code == 404


def test_download_failed_certificate_returns_409(client, submit_job):
    _, status = submit_job([{"name": "Bad", "email": "nope"}, {"name": "Ok", "email": "o@x.com"}])
    failed = status["certificates"][0]
    response = client.get(f"/certificates/{failed['id']}/download")
    assert response.status_code == 409
    assert "failed" in response.json()["detail"]


def test_download_when_file_was_deleted_returns_404(client, submit_job, fetch_job):
    job_id, status = submit_job()
    cert = fetch_job(job_id).certificates[0]
    import os
    os.remove(cert.file_path)

    response = client.get(f"/certificates/{cert.id}/download")
    assert response.status_code == 404
    assert "missing" in response.json()["detail"]


def test_download_pending_certificate_returns_409(client, session_factory):
    session = session_factory()
    job = Job(course_name="C", issued_by="I", issue_date=date(2026, 10, 1), total=1)
    job.certificates.append(Certificate(row_index=0, recipient_name="A", status="pending"))
    session.add(job)
    session.commit()
    cert_id = job.certificates[0].id
    session.close()

    assert client.get(f"/certificates/{cert_id}/download").status_code == 409


# --------------------------------------------------------------- job ZIP
def test_download_job_zip(client, submit_job, make_recipients):
    job_id, _ = submit_job(make_recipients(3))
    response = client.get(f"/jobs/{job_id}/download")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert f"certificates_{job_id}.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        assert zf.namelist() == ["0001_Student_1.pdf", "0002_Student_2.pdf", "0003_Student_3.pdf"]
        assert all(zf.read(n).startswith(b"%PDF-") for n in zf.namelist())


def test_zip_contains_only_successful_certificates(client, submit_job, make_recipients):
    good = make_recipients(2)
    job_id, status = submit_job([good[0], {"name": "Bad", "email": "nope"}, good[1]])
    assert status["status"] == "completed_with_errors"

    with zipfile.ZipFile(io.BytesIO(client.get(f"/jobs/{job_id}/download").content)) as zf:
        assert zf.namelist() == ["0001_Student_1.pdf", "0003_Student_2.pdf"]


def test_zip_for_unknown_job_returns_404(client):
    assert client.get("/jobs/nope/download").status_code == 404


def test_zip_when_nothing_was_generated_returns_404(client, submit_job):
    job_id, _ = submit_job([{}, {"name": "x", "email": "bad"}])
    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 404
    assert "No certificates" in response.json()["detail"]


def test_zip_while_job_is_running_returns_409(client, session_factory):
    session = session_factory()
    job = Job(course_name="C", issued_by="I", issue_date=date(2026, 10, 1),
              status="processing", total=1)
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()

    response = client.get(f"/jobs/{job_id}/download")
    assert response.status_code == 409
    assert "still running" in response.json()["detail"]


def test_health_endpoint(client):
    assert client.get("/health").json() == {"status": "ok"}