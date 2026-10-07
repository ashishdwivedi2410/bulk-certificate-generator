from datetime import date

from sqlalchemy import func, select

from app.db.models import Certificate, CertificateStatus, Job, JobStatus


def make_job(**kwargs):
    defaults = dict(course_name="Python 101", issued_by="Acme", issue_date=date(2026, 10, 1))
    defaults.update(kwargs)
    return Job(**defaults)


def test_job_defaults(db):
    job = make_job()
    db.add(job)
    db.commit()

    assert len(job.id) == 36  # uuid string
    assert job.status == JobStatus.PENDING.value
    assert (job.total, job.succeeded, job.failed) == (0, 0, 0)
    assert job.created_at is not None
    assert job.completed_at is None


def test_certificate_defaults_and_nullable_fields(db):
    job = make_job()
    job.certificates.append(Certificate(row_index=0))  # no name / email at all
    db.add(job)
    db.commit()

    cert = job.certificates[0]
    assert cert.status == CertificateStatus.PENDING.value
    assert cert.recipient_name is None
    assert cert.recipient_email is None
    assert cert.file_path is None
    assert cert.error_message is None


def test_ids_are_unique(db):
    a, b = make_job(), make_job()
    db.add_all([a, b])
    db.commit()
    assert a.id != b.id


def test_processed_and_progress_percent():
    job = make_job(total=4, succeeded=1, failed=1)
    assert job.processed == 2
    assert job.progress_percent == 50.0


def test_progress_percent_when_total_is_zero():
    assert make_job(total=0, succeeded=0, failed=0).progress_percent == 100.0


def test_progress_percent_is_rounded():
    assert make_job(total=3, succeeded=1, failed=0).progress_percent == 33.33


def test_relationship_both_directions_and_ordering(db):
    job = make_job()
    job.certificates = [
        Certificate(row_index=2, recipient_name="C"),
        Certificate(row_index=0, recipient_name="A"),
        Certificate(row_index=1, recipient_name="B"),
    ]
    db.add(job)
    db.commit()
    db.expire_all()

    loaded = db.get(Job, job.id)
    assert [c.recipient_name for c in loaded.certificates] == ["A", "B", "C"]
    assert loaded.certificates[0].job.id == job.id
    assert loaded.certificates[0].job_id == job.id


def test_deleting_job_deletes_its_certificates(db):
    job = make_job()
    job.certificates = [Certificate(row_index=0), Certificate(row_index=1)]
    db.add(job)
    db.commit()

    db.delete(job)
    db.commit()

    assert db.execute(select(func.count()).select_from(Certificate)).scalar_one() == 0


def test_status_enums_are_plain_strings():
    # stored as strings, so comparing with literals must work
    assert JobStatus.COMPLETED == "completed"
    assert CertificateStatus.FAILED == "failed"