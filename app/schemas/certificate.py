"""Schemas for a single recipient and a single certificate result."""
from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator


class RecipientInput(BaseModel):
    """One recipient. Validated per row inside job_service, NOT at request level,
    so one bad row is recorded as a failed certificate instead of rejecting
    the whole request."""

    name: str = Field(min_length=1, max_length=100)
    email: EmailStr

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v


class CertificateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    row_index: int
    recipient_name: str | None
    recipient_email: str | None
    status: str
    error_message: str | None

    @computed_field
    @property
    def download_url(self) -> str | None:
        """Only successful certificates can be downloaded."""
        if self.status == "success":
            return f"/certificates/{self.id}/download"
        return None