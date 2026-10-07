"""SQLAlchemy engine, session factory and table creation."""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# SQLite needs check_same_thread=False because FastAPI runs the request
# handler and the background task in different threads.
_connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create all tables if they do not exist yet."""
    from app.db import models  # noqa: F401  (registers the models on Base)

    Base.metadata.create_all(bind=engine)