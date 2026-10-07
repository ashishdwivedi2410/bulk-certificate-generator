"""Schemas for creating a job and reporting its status."""
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import settings
from app.schemas.certificate import CertificateResponse


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite drops timezone info. Everything is stored in UTC, so put it back
    to make the API output unambiguous (e.g. 2026-10-01T10:00:00Z)."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class JobCreateRequest(BaseModel):
    course_name: str = Field(min_length=1, max_length=200)
    issued_by: str = Field(min_length=1, max_length=200)
    issue_date: date
    # Deliberately loose (list of dicts): each row is validated individually
    # later so invalid rows become failed certificates, not a 422 for everyone.
    recipients: list[dict[str, Any]] = Field(min_length=1)

    @field_validator("recipients")
    @classmethod
    def check_max_recipients(cls, v: list) -> list:
        limit = settings.max_recipients_per_job  # read at call time so tests can change it
        if len(v) > limit:
            raise ValueError(f"A job can contain at most {limit} recipients")
        return v


class JobCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    status: str
    total: int
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_utc(cls, v):
        return _as_utc(v)

    @computed_field
    @property
    def status_url(self) -> str:
        return f"/jobs/{self.id}"


class JobStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    course_name: str
    issued_by: str
    issue_date: date
    status: str
    total: int
    succeeded: int
    failed: int
    processed: int
    progress_percent: float
    created_at: datetime
    completed_at: datetime | None
    certificates: list[CertificateResponse]

    @field_validator("created_at", "completed_at")
    @classmethod
    def _timestamps_utc(cls, v):
        return _as_utc(v)