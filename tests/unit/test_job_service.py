from datetime import date

import pytest

from app.db.models import CertificateStatus, JobStatus
from app.schemas.job import JobCreateRequest
from app.services import job_service
from app.services.job_service import status_from_counts


def make_request(recipients, **overrides):
    data = dict(
        course_name="Python 101",
        issued_by="Acme",
        issue_date="2026-10-01",
        recipients=recipients,
    )
    data.update(overrides)
    return JobCreateRequest(**data)


GOOD = {"name": "Asha", "email": "asha@example.com"}


def test_create_job_with_valid_recipients(db):
    job = job_service.create_job(db, make_request([GOOD, {"name": "Ravi", "email": "r@example.com"}]))

    assert job.status == JobStatus.PENDING.value
    assert (job.total, job.succeeded, job.failed) == (2, 0, 0)
    assert job.issue_date == date(2026, 10, 1)
    assert [c.status for c in job.certificates] == ["pending", "pending"]
    assert [c.row_index for c in job.certificates] == [0, 1]
    assert job.completed_at is None


def test_create_job_strips_whitespace(db):
    job = job_service.create_job(
        db,
        make_request([{"name": "  Asha  ", "email": "asha@example.com"}],
                     course_name="  Python 101  ", issued_by="  Acme  "),
    )
    assert job.course_name == "Python 101"
    assert job.issued_by == "Acme"
    assert job.certificates[0].recipient_name == "Asha"


def test_invalid_rows_are_recorded_as_failed_not_dropped(db):
    job = job_service.create_job(
        db, make_request([GOOD, {"name": "Bad", "email": "nope"}, GOOD])
    )

    assert job.total == 3
    assert job.failed == 1
    assert job.status == JobStatus.PENDING.value  # valid rows still to be processed
    bad = job.certificates[1]
    assert bad.status == CertificateStatus.FAILED.value
    assert bad.row_index == 1
    assert "email" in bad.error_message
    # what the client sent is kept so the row can be identified
    assert bad.recipient_name == "Bad"
    assert bad.recipient_email == "nope"


def test_empty_row_reports_every_missing_field(db):
    job = job_service.create_job(db, make_request([GOOD, {}]))
    bad = job.certificates[1]
    assert bad.recipient_name is None and bad.recipient_email is None
    assert "name" in bad.error_message and "email" in bad.error_message


def test_non_string_values_in_a_row_are_recorded_not_crashing(db):
    job = job_service.create_job(db, make_request([GOOD, {"name": 123, "email": ["x"]}]))
    bad = job.certificates[1]
    assert bad.status == "failed"
    assert bad.recipient_name == "123"


def test_extra_fields_in_a_row_are_ignored(db):
    job = job_service.create_job(db, make_request([{**GOOD, "phone": "999"}]))
    assert job.certificates[0].status == "pending"


def test_job_where_every_row_is_invalid_is_finalized_immediately(db):
    job = job_service.create_job(db, make_request([{}, {"name": "x", "email": "bad"}]))
    assert job.status == JobStatus.FAILED.value
    assert job.failed == job.total == 2
    assert job.completed_at is not None


def test_get_job_returns_job_with_certificates(db):
    created = job_service.create_job(db, make_request([GOOD]))
    found = job_service.get_job(db, created.id)
    assert found.id == created.id
    assert len(found.certificates) == 1


def test_get_job_unknown_id_returns_none(db):
    assert job_service.get_job(db, "does-not-exist") is None


def test_mark_processing(db):
    job = job_service.create_job(db, make_request([GOOD]))
    job_service.mark_processing(db, job)
    assert job.status == JobStatus.PROCESSING.value


def test_finalize_job_sets_status_and_completed_at(db):
    job = job_service.create_job(db, make_request([GOOD]))
    job.succeeded = 1
    job_service.finalize_job(job)
    assert job.status == JobStatus.COMPLETED.value
    assert job.completed_at is not None


@pytest.mark.parametrize(
    "total, succeeded, failed, expected",
    [
        (3, 3, 0, JobStatus.COMPLETED),
        (3, 2, 1, JobStatus.COMPLETED_WITH_ERRORS),
        (3, 1, 2, JobStatus.COMPLETED_WITH_ERRORS),
        (3, 0, 3, JobStatus.FAILED),
    ],
)
def test_status_from_counts(total, succeeded, failed, expected):
    assert status_from_counts(total, succeeded, failed) == expected