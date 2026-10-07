"""Shared FastAPI dependencies."""
from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.database import SessionLocal


def get_db() -> Generator[Session, None, None]:
    """Yield one DB session per request and always close it afterwards.

    Tests override this dependency to point at an in-memory database.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()