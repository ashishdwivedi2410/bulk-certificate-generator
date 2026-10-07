from pathlib import Path

import pytest

from app import workers
from app.db.models import JobStatus
from app.schemas.job import JobCreateRequest
from app.services import generator_service, job_service


def create_job(db, recipients):
    return job_service.create_job(
        db,
        JobCreateRequest(
            course_name="Python 101",
            issued_by="Acme",
            issue_date="2026-10-01",
            recipients=recipients,
        ),
    )


def run(job, session_factory):
    workers.process_job(job.id, session_factory=session_factory)


def students(n):
    return [{"name": f"Student {i}", "email": f"s{i}@example.com"} for i in range(1, n + 1)]


def test_all_valid_certificates_succeed(db, session_factory, fetch_job):
    job = create_job(db, students(3))
    run(job, session_factory)

    done = fetch_job(job.id)
    assert done.status == JobStatus.COMPLETED.value
    assert (done.total, done.succeeded, done.failed) == (3, 3, 0)
    assert done.completed_at is not None
    for cert in done.certificates:
        assert cert.status == "success"
        assert Path(cert.file_path).read_bytes().startswith(b"%PDF")


def test_one_failure_does_not_stop_the_others(db, session_factory, fetch_job, monkeypatch):
    real = generator_service.generate_certificate

    def flaky(**kwargs):
        if kwargs["recipient_name"] == "Student 2":
            raise RuntimeError("boom")
        return real(**kwargs)

    monkeypatch.setattr(generator_service, "generate_certificate", flaky)
    job = create_job(db, students(4))
    run(job, session_factory)

    done = fetch_job(job.id)
    statuses = [c.status for c in done.certificates]
    assert statuses == ["success", "failed", "success", "success"]
    assert done.status == JobStatus.COMPLETED_WITH_ERRORS.value
    assert (done.succeeded, done.failed) == (3, 1)
    failed = done.certificates[1]
    assert failed.error_message == "boom"
    assert failed.file_path is None


def test_every_certificate_failing_marks_job_failed(db, session_factory, fetch_job, monkeypatch):
    def always_fail(**kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(generator_service, "generate_certificate", always_fail)
    job = create_job(db, students(3))
    run(job, session_factory)

    done = fetch_job(job.id)
    assert done.status == JobStatus.FAILED.value
    assert (done.succeeded, done.failed) == (0, 3)


def test_counters_include_rows_that_failed_validation(db, session_factory, fetch_job):
    job = create_job(db, [students(1)[0], {"name": "Bad", "email": "nope"}, students(2)[1]])
    assert job.failed == 1  # counted at creation

    run(job, session_factory)

    done = fetch_job(job.id)
    assert (done.total, done.succeeded, done.failed) == (3, 2, 1)
    assert done.succeeded + done.failed == done.total
    assert done.status == JobStatus.COMPLETED_WITH_ERRORS.value
    assert done.certificates[1].file_path is None  # worker never touched it


def test_real_render_failure_is_isolated(db, session_factory, fetch_job):
    # non-Latin name passes validation but cannot be rendered
    job = create_job(db, [students(1)[0], {"name": "राहुल", "email": "r@example.com"}])
    run(job, session_factory)

    done = fetch_job(job.id)
    assert [c.status for c in done.certificates] == ["success", "failed"]
    assert "cannot render" in done.certificates[1].error_message


def test_error_message_is_truncated(db, session_factory, fetch_job, monkeypatch):
    def noisy(**kwargs):
        raise RuntimeError("x" * 5000)

    monkeypatch.setattr(generator_service, "generate_certificate", noisy)
    job = create_job(db, students(1))
    run(job, session_factory)

    assert len(fetch_job(job.id).certificates[0].error_message) == 1000


def test_files_are_stored_per_job(db, session_factory, fetch_job, output_dir):
    job = create_job(db, students(2))
    run(job, session_factory)

    for cert in fetch_job(job.id).certificates:
        assert Path(cert.file_path).parent == output_dir / job.id


def test_running_a_job_twice_does_not_double_count(db, session_factory, fetch_job):
    job = create_job(db, students(2))
    run(job, session_factory)
    run(job, session_factory)

    done = fetch_job(job.id)
    assert (done.succeeded, done.failed) == (2, 0)


def test_unknown_job_id_is_a_noop(session_factory):
    workers.process_job("does-not-exist", session_factory=session_factory)  # must not raise


def test_job_is_processing_while_worker_runs(db, session_factory, fetch_job, monkeypatch):
    seen = []
    real = generator_service.generate_certificate
    job = create_job(db, students(2))

    def spy(**kwargs):
        seen.append(fetch_job(job.id).status)
        return real(**kwargs)

    monkeypatch.setattr(generator_service, "generate_certificate", spy)
    run(job, session_factory)

    assert seen == ["processing", "processing"]


def test_progress_is_committed_after_each_certificate(db, session_factory, fetch_job, monkeypatch):
    seen = []
    real = generator_service.generate_certificate
    job = create_job(db, students(3))

    def spy(**kwargs):
        seen.append(fetch_job(job.id).succeeded)  # what a polling client would see
        return real(**kwargs)

    monkeypatch.setattr(generator_service, "generate_certificate", spy)
    run(job, session_factory)

    assert seen == [0, 1, 2]


def test_unexpected_crash_does_not_leave_job_stuck(db, session_factory, fetch_job, monkeypatch):
    def crash(*args, **kwargs):
        raise RuntimeError("infrastructure down")

    monkeypatch.setattr(workers, "_process_one", crash)
    job = create_job(db, students(2))
    run(job, session_factory)

    done = fetch_job(job.id)
    assert done.status == JobStatus.FAILED.value
    assert [c.status for c in done.certificates] == ["failed", "failed"]
    assert "aborted" in done.certificates[0].error_message
    assert done.succeeded + done.failed == done.total