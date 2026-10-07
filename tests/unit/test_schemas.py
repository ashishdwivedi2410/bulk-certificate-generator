import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.certificate import CertificateResponse, RecipientInput
from app.schemas.job import JobCreateRequest, JobCreateResponse


def valid_request(**overrides):
    data = dict(
        course_name="Python 101",
        issued_by="Acme",
        issue_date="2026-10-01",
        recipients=[{"name": "Asha", "email": "asha@example.com"}],
    )
    data.update(overrides)
    return data


# ------------------------------------------------------- RecipientInput
def test_recipient_valid():
    r = RecipientInput(name="Asha Verma", email="asha@example.com")
    assert r.name == "Asha Verma"
    assert str(r.email) == "asha@example.com"


def test_recipient_name_is_stripped():
    assert RecipientInput(name="  Asha  ", email="a@example.com").name == "Asha"


@pytest.mark.parametrize("name", ["", "   "])
def test_recipient_blank_name_rejected(name):
    with pytest.raises(ValidationError):
        RecipientInput(name=name, email="a@example.com")


def test_recipient_name_too_long_rejected():
    with pytest.raises(ValidationError):
        RecipientInput(name="x" * 101, email="a@example.com")


@pytest.mark.parametrize("email", ["", "plain", "a@", "@x.com", "a b@x.com"])
def test_recipient_invalid_email_rejected(email):
    with pytest.raises(ValidationError):
        RecipientInput(name="Asha", email=email)


def test_recipient_missing_fields_rejected():
    with pytest.raises(ValidationError) as exc:
        RecipientInput.model_validate({})
    assert {e["loc"][0] for e in exc.value.errors()} == {"name", "email"}


# ----------------------------------------------------- JobCreateRequest
def test_job_request_valid():
    req = JobCreateRequest(**valid_request())
    assert req.course_name == "Python 101"
    assert len(req.recipients) == 1


def test_job_request_accepts_bad_rows_at_this_level():
    # Row-level validation happens later, so one bad row must NOT reject the request.
    req = JobCreateRequest(**valid_request(recipients=[{"name": "x"}, {}, {"email": "bad"}]))
    assert len(req.recipients) == 3


@pytest.mark.parametrize(
    "overrides",
    [
        {"recipients": []},
        {"recipients": ["not-a-dict"]},
        {"course_name": ""},
        {"issued_by": ""},
        {"issue_date": "not-a-date"},
        {"course_name": "x" * 201},
    ],
)
def test_job_request_invalid(overrides):
    with pytest.raises(ValidationError):
        JobCreateRequest(**valid_request(**overrides))


@pytest.mark.parametrize("missing", ["course_name", "issued_by", "issue_date", "recipients"])
def test_job_request_required_fields(missing):
    data = valid_request()
    del data[missing]
    with pytest.raises(ValidationError):
        JobCreateRequest(**data)


def test_job_request_max_recipients(monkeypatch):
    monkeypatch.setattr(settings, "max_recipients_per_job", 2)
    JobCreateRequest(**valid_request(recipients=[{}, {}]))  # at the limit: ok
    with pytest.raises(ValidationError) as exc:
        JobCreateRequest(**valid_request(recipients=[{}, {}, {}]))
    assert "at most 2" in str(exc.value)


# ------------------------------------------------------ response schemas
def test_job_create_response_has_status_url():
    from datetime import datetime

    resp = JobCreateResponse(id="abc", status="pending", total=1, created_at=datetime.now())
    assert resp.status_url == "/jobs/abc"


def _cert(status):
    return CertificateResponse(
        id="c1", row_index=0, recipient_name="A", recipient_email="a@x.com",
        status=status, error_message=None,
    )


def test_download_url_only_for_successful_certificates():
    assert _cert("success").download_url == "/certificates/c1/download"
    assert _cert("failed").download_url is None
    assert _cert("pending").download_url is None


def test_naive_datetimes_are_exposed_as_utc():
    from datetime import datetime, timezone

    naive = datetime(2026, 10, 1, 10, 0, 0)  # what SQLite hands back
    resp = JobCreateResponse(id="abc", status="pending", total=1, created_at=naive)
    assert resp.created_at.tzinfo == timezone.utc
    assert resp.model_dump_json().count("2026-10-01T10:00:00Z") == 1