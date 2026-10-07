FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first so this layer is cached until requirements change
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY templates ./templates

# Run as a non-root user. /data holds the SQLite file and generated PDFs;
# it is created BEFORE declaring the volume so a new volume inherits this owner.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /data && chown -R appuser:appuser /data /app
ENV DATABASE_URL=sqlite:////data/certificates.db \
    GENERATED_DIR=/data/generated
VOLUME /data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# One worker on purpose: generation runs in-process (see README, design decisions)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]