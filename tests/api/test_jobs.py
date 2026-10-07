from datetime import date

from app.db.models import Certificate, Job


def test_create_job_returns_202_with_job_info(client, payload_factory):
    response = client.post("/jobs", json=payload_factory())

    assert response.status_code == 202
    body = response.json()
    assert len(body["id"]) == 36
    assert body["status"] == "pending"  # response is sent before generation starts
    assert body["total"] == 2
    assert body["status_url"] == f"/jobs/{body['id']}"
    assert "created_at" in body


def test_status_url_from_response_works(client, payload_factory):
    created = client.post("/jobs", json=payload_factory()).json()
    assert client.get(created["status_url"]).status_code == 200


def test_job_is_persisted(client, payload_factory, fetch_job):
    job_id = client.post("/jobs", json=payload_factory()).json()["id"]
    job = fetch_job(job_id)
    assert job.course_name == "Python 101"
    assert job.issued_by == "Acme Academy"
    assert job.issue_date == date(2026, 10, 1)
    assert len(job.certificates) == 2


def test_status_of_finished_job(submit_job):
    _, status = submit_job()

    assert status["status"] == "completed"
    assert status["course_name"] == "Python 101"
    assert status["total"] == 2
    assert status["succeeded"] == 2
    assert status["failed"] == 0
    assert status["processed"] == 2
    assert status["progress_percent"] == 100.0
    assert status["completed_at"] is not None
    assert len(status["certificates"]) == 2


def test_status_lists_each_recipient_in_submitted_order(submit_job, make_recipients):
    _, status = submit_job(make_recipients(5))
    assert [c["row_index"] for c in status["certificates"]] == [0, 1, 2, 3, 4]
    assert [c["recipient_name"] for c in status["certificates"]] == [f"Student {i}" for i in range(1, 6)]
    assert all(c["download_url"] for c in status["certificates"])


def test_unknown_job_returns_404(client):
    response = client.get("/jobs/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def _insert_job(session_factory, *, status, succeeded, failed, cert_statuses):
    session = session_factory()
    job = Job(
        course_name="C", issued_by="I", issue_date=date(2026, 10, 1),
        status=status, total=len(cert_statuses), succeeded=succeeded, failed=failed,
    )
    for i, st in enumerate(cert_statuses):
        job.certificates.append(Certificate(row_index=i, recipient_name=f"R{i}", status=st))
    session.add(job)
    session.commit()
    job_id = job.id
    session.close()
    return job_id


def test_progress_of_a_job_that_has_not_started(client, session_factory):
    job_id = _insert_job(session_factory, status="pending", succeeded=0, failed=0,
                         cert_statuses=["pending"] * 4)
    body = client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "pending"
    assert body["progress_percent"] == 0.0
    assert body["processed"] == 0
    assert all(c["download_url"] is None for c in body["certificates"])


def test_progress_of_a_job_in_flight(client, session_factory):
    job_id = _insert_job(session_factory, status="processing", succeeded=1, failed=1,
                         cert_statuses=["success", "failed", "pending", "pending"])
    body = client.get(f"/jobs/{job_id}").json()

    assert body["status"] == "processing"
    assert body["processed"] == 2
    assert body["progress_percent"] == 50.0
    assert body["completed_at"] is None


def test_jobs_are_independent(submit_job, make_recipients):
    id_a, status_a = submit_job(make_recipients(2))
    id_b, status_b = submit_job(make_recipients(5))

    assert id_a != id_b
    assert status_a["total"] == 2 and status_b["total"] == 5
    assert {c["id"] for c in status_a["certificates"]}.isdisjoint(
        {c["id"] for c in status_b["certificates"]}
    )


def test_timestamps_are_explicit_utc(client, payload_factory):
    created = client.post("/jobs", json=payload_factory()).json()
    status = client.get(created["status_url"]).json()

    assert created["created_at"].endswith("Z")
    assert status["created_at"].endswith("Z")
    assert status["completed_at"].endswith("Z")
    assert status["completed_at"] >= status["created_at"]