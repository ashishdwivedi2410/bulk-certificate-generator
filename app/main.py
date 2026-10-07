"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import certificates, jobs
from app.core.config import settings
from app.db.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables and the output folder on startup.
    init_db()
    settings.generated_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="Bulk Certificate Generator",
    description="Submit many recipients, get certificates generated in the background.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(jobs.router)
app.include_router(certificates.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}