"""Shared fixtures.

Isolation rules for every test:
  * database  -> a fresh in-memory SQLite DB (never certificates.db)
  * files     -> a temp folder (never the real generated/ folder)
  * the app's own DB session and the background worker's session are both
    pointed at that in-memory DB
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import workers
from app.api.deps import get_db
from app.core.config import settings
from app.db import models  # noqa: F401  (registers tables on Base)
from app.db.database import Base
from app.main import app as fastapi_app
from app.services import job_service


def pytest_collection_modifyitems(items):
    """Auto-mark tests by folder so `pytest -m unit` / `-m api` work."""
    for item in items:
        path = str(item.fspath).replace("\\", "/")
        if "/tests/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "/tests/api/" in path:
            item.add_marker(pytest.mark.api)


# ---------------------------------------------------------------- database
@pytest.fixture
def engine():
    # StaticPool keeps ONE connection, so the request thread and the
    # background-task thread see the same in-memory database.
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


@pytest.fixture
def fetch_job(session_factory):
    """Read a job with its certificates through a fresh session."""

    def _fetch(job_id):
        session = session_factory()
        try:
            return job_service.get_job(session, job_id)
        finally:
            session.close()  # loaded attributes stay readable after close

    return _fetch


# ------------------------------------------------------------------- files
@pytest.fixture(autouse=True)
def output_dir(tmp_path, monkeypatch):
    path = tmp_path / "generated"
    path.mkdir()
    monkeypatch.setattr(settings, "generated_dir", path)
    return path


# --------------------------------------------------------------------- app
@pytest.fixture
def client(session_factory, monkeypatch):
    def _override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    # The background worker opens its own session via this module-level name.
    monkeypatch.setattr(workers, "SessionLocal", session_factory)
    # No `with` block on purpose: skips the startup hook, which would create
    # tables on the real engine. Background tasks still run before returning.
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


# ---------------------------------------------------------- data factories
@pytest.fixture
def make_recipients():
    def _make(n=2):
        return [
            {"name": f"Student {i}", "email": f"student{i}@example.com"}
            for i in range(1, n + 1)
        ]

    return _make


@pytest.fixture
def payload_factory(make_recipients):
    def _make(recipients=None, **overrides):
        payload = {
            "course_name": "Python 101",
            "issued_by": "Acme Academy",
            "issue_date": "2026-10-01",
            "recipients": make_recipients(2) if recipients is None else recipients,
        }
        payload.update(overrides)
        return payload

    return _make


@pytest.fixture
def submit_job(client, payload_factory):
    """POST a job, then return (job_id, status_json). The background task has
    already finished by the time the test client returns."""

    def _submit(recipients=None, **overrides):
        response = client.post("/jobs", json=payload_factory(recipients, **overrides))
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        status = client.get(f"/jobs/{job_id}")
        assert status.status_code == 200, status.text
        return job_id, status.json()

    return _submit