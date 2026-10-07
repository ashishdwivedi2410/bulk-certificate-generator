import pytest

from app.core.config import settings


# ---------------------------------------------- request-level problems -> 422
@pytest.mark.parametrize(
    "overrides",
    [
        {"recipients": []},
        {"recipients": "not-a-list"},
        {"recipients": ["just-a-string"]},
        {"course_name": ""},
        {"issued_by": ""},
        {"issue_date": "01/10/2026"},
        {"issue_date": "not-a-date"},
    ],
)
def test_bad_request_is_rejected_with_422(client, payload_factory, overrides):
    response = client.post("/jobs", json=payload_factory(**overrides))
    assert response.status_code == 422


@pytest.mark.parametrize("missing", ["course_name", "issued_by", "issue_date", "recipients"])
def test_missing_required_field_is_rejected(client, payload_factory, missing):
    payload = payload_factory()
    del payload[missing]
    response = client.post("/jobs", json=payload)
    assert response.status_code == 422
    assert missing in str(response.json()["detail"])


def test_empty_body_is_rejected(client):
    assert client.post("/jobs", json={}).status_code == 422


def test_too_many_recipients_is_rejected(client, payload_factory, make_recipients, monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 3)
    assert client.post("/jobs", json=payload_factory(make_recipients(3))).status_code == 202
    assert client.post("/jobs", json=payload_factory(make_recipients(4))).status_code == 422


def test_rejected_request_creates_no_job(client, payload_factory, session_factory):
    from sqlalchemy import func, select

    from app.db.models import Job

    client.post("/jobs", json=payload_factory(recipients=[]))
    session = session_factory()
    assert session.execute(select(func.count()).select_from(Job)).scalar_one() == 0
    session.close()


# ------------------------- row-level problems -> accepted, row marked failed
@pytest.mark.parametrize(
    "bad_row, field",
    [
        ({"email": "a@example.com"}, "name"),
        ({"name": "   ", "email": "a@example.com"}, "name"),
        ({"name": "x" * 101, "email": "a@example.com"}, "name"),
        ({"name": "Bob"}, "email"),
        ({"name": "Bob", "email": "not-an-email"}, "email"),
        ({"name": "Bob", "email": ""}, "email"),
        ({}, "name"),
    ],
)
def test_invalid_row_is_reported_but_does_not_block_valid_rows(
    submit_job, make_recipients, bad_row, field
):
    good = make_recipients(2)
    _, status = submit_job([good[0], bad_row, good[1]])

    assert status["total"] == 3
    assert status["succeeded"] == 2
    assert status["failed"] == 1
    assert status["status"] == "completed_with_errors"

    bad = status["certificates"][1]
    assert bad["row_index"] == 1
    assert bad["status"] == "failed"
    assert field in bad["error_message"]
    assert bad["download_url"] is None
    assert status["certificates"][0]["status"] == "success"
    assert status["certificates"][2]["status"] == "success"


def test_every_row_invalid_job_is_accepted_and_failed(client, submit_job):
    job_id, status = submit_job([{}, {"name": "A", "email": "bad"}])

    assert status["status"] == "failed"
    assert (status["succeeded"], status["failed"]) == (0, 2)
    assert status["progress_percent"] == 100.0
    assert client.get(f"/jobs/{job_id}/download").status_code == 404


def test_valid_row_with_extra_fields_still_succeeds(submit_job):
    _, status = submit_job([{"name": "Asha", "email": "a@example.com", "phone": "123"}])
    assert status["status"] == "completed"


def test_name_whitespace_is_trimmed(submit_job):
    _, status = submit_job([{"name": "  Asha  ", "email": "a@example.com"}])
    assert status["certificates"][0]["recipient_name"] == "Asha"


def test_non_string_values_are_reported_not_a_server_error(submit_job):
    _, status = submit_job([{"name": 42, "email": None}])
    assert status["certificates"][0]["status"] == "failed"