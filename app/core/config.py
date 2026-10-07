"""Application settings, read from environment variables with safe defaults."""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[2]  # project root

# Optional .env file at the project root. Variables already set in the real
# environment take precedence (load_dotenv does not override them).
load_dotenv(BASE_DIR / ".env")


@dataclass
class Settings:
    # Not frozen on purpose: tests override these values (e.g. a temp output dir).
    database_url: str = field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
    )
    generated_dir: Path = field(
        default_factory=lambda: Path(os.getenv("GENERATED_DIR", str(BASE_DIR / "generated")))
    )
    template_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TEMPLATE_DIR", str(BASE_DIR / "templates")))
    )
    # Upper bound per request so one call cannot queue unbounded work.
    max_recipients_per_job: int = field(
        default_factory=lambda: int(os.getenv("MAX_RECIPIENTS_PER_JOB", "5000"))
    )


settings = Settings()