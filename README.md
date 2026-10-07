# Bulk Certificate Generator

A backend API that accepts **one request containing many recipients**, generates a PDF
certificate for each valid recipient from a single predefined template, and lets the
client track progress and download the results.

- **Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite (any SQLAlchemy database works), ReportLab
- **Processing:** background task. `POST /jobs` returns `202` immediately; the client polls for progress.
- **Failure handling:** one bad recipient never blocks the others, and the job status says exactly which rows failed and why.

---

## Table of contents

1. [Setup](#1-setup)
2. [Run the application](#2-run-the-application)
3. [Run the tests](#3-run-the-tests)
4. [Submit a certificate generation request](#4-submit-a-certificate-generation-request)
5. [Check progress](#5-check-progress)
6. [Retrieve generated certificates](#6-retrieve-generated-certificates)
7. [API reference](#7-api-reference)
8. [Configuration](#8-configuration)
9. [Design decisions](#9-design-decisions)
10. [Deployment to AWS EC2](#10-deployment-to-aws-ec2)
11. [Known limitations and next steps](#11-known-limitations-and-next-steps)
12. [Project structure](#12-project-structure)

---

## 1. Setup

Requires Python 3.12 (developed and tested on 3.12; 3.10+ should work).

```bash
git clone <repo-url> bulk-certificate-generator
cd bulk-certificate-generator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements-dev.txt   # runtime + test dependencies
# (use requirements.txt instead if you only want to run the app)

cp .env.example .env               # optional: every setting has a default
```

No database setup is needed. The default SQLite database and its tables are created
automatically on first start.

## 2. Run the application

```bash
uvicorn app.main:app --reload
```

- API: <http://localhost:8000>
- Interactive docs (try every endpoint in the browser): <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

### With Docker

```bash
docker compose up --build
```

The API is served on port 8000. The SQLite file and the generated PDFs are kept in the
`certificate_data` volume, so they survive restarts. `docker compose down -v` deletes them.

## 3. Run the tests

```bash
pytest                 # everything (146 tests, ~3 seconds)
pytest -m unit         # only unit tests (no HTTP)
pytest -m api          # only API tests
pytest tests/api/test_failure_handling.py
```

The tests never touch your real database or `generated/` folder: each test gets a fresh
in-memory SQLite database and a temporary output directory.

| Area (brief requirement) | Where it is tested |
|---|---|
| Creating a generation job | `api/test_jobs.py`, `unit/test_job_service.py` |
| Input validation | `api/test_validation.py`, `unit/test_schemas.py` |
| Certificate generation | `api/test_generation.py`, `unit/test_generator_service.py` |
| Job status / progress | `api/test_jobs.py`, `unit/test_workers.py` |
| One certificate failing | `api/test_failure_handling.py`, `unit/test_workers.py` |
| Retrieving certificates | `api/test_certificates.py`, `unit/test_certificate_service.py` |
| Models | `unit/test_models.py` |

## 4. Submit a certificate generation request

`POST /jobs` with the certificate details and a list of recipients:

```bash
curl -i -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "course_name": "Python for Beginners",
    "issued_by": "Acme Academy",
    "issue_date": "2026-10-01",
    "recipients": [
      {"name": "Asha Verma",  "email": "asha@example.com"},
      {"name": "Ravi Kumar",  "email": "not-an-email"},
      {"name": "Meera Iyer",  "email": "meera@example.com"}
    ]
  }'
```

Response: `202 Accepted`

```json
{
  "id": "65ae1438-2d60-405e-80f1-e75679955d80",
  "status": "pending",
  "total": 3,
  "created_at": "2026-10-07T19:18:10.916567Z",
  "status_url": "/jobs/65ae1438-2d60-405e-80f1-e75679955d80"
}
```

The request is accepted even though row 2 has an invalid email. See
[Validation](#validation) for what is rejected outright and what is recorded per row.

### Validation

| Problem | Result |
|---|---|
| Missing/empty `course_name` or `issued_by`, bad `issue_date`, empty `recipients`, more than `MAX_RECIPIENTS_PER_JOB` recipients | **`422`**, nothing is created |
| A single recipient with a missing/blank name (max 100 chars) or an invalid email | **`202`**, that row is recorded as `failed` with an error message; all other rows are still generated |

## 5. Check progress

```bash
curl http://localhost:8000/jobs/<job-id>
```

```json
{
  "id": "e13c7d35-1555-4f42-ba7d-879156d09b74",
  "course_name": "Python for Beginners",
  "issued_by": "Acme Academy",
  "issue_date": "2026-10-01",
  "status": "completed_with_errors",
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "processed": 3,
  "progress_percent": 100.0,
  "created_at": "2026-10-07T19:18:10.949364Z",
  "completed_at": "2026-10-07T19:18:11.013663Z",
  "certificates": [
    {
      "id": "098aa058-9447-427e-ad39-dfab83ca2023",
      "row_index": 0,
      "recipient_name": "Asha Verma",
      "recipient_email": "asha@example.com",
      "status": "success",
      "error_message": null,
      "download_url": "/certificates/098aa058-9447-427e-ad39-dfab83ca2023/download"
    },
    {
      "id": "c18ca494-ec1f-4979-8eb0-69685c0b89db",
      "row_index": 1,
      "recipient_name": "Ravi Kumar",
      "recipient_email": "not-an-email",
      "status": "failed",
      "error_message": "email: value is not a valid email address: An email address must have an @-sign.",
      "download_url": null
    },
    {
      "id": "3a9a9fc9-2a73-48c9-9cb8-505abec6250f",
      "row_index": 2,
      "recipient_name": "Meera Iyer",
      "recipient_email": "meera@example.com",
      "status": "success",
      "error_message": null,
      "download_url": "/certificates/3a9a9fc9-2a73-48c9-9cb8-505abec6250f/download"
    }
  ]
}
```

- `row_index` is the position of the recipient in the list you sent (starting at 0), so
  every result, including invalid rows, can be matched back to your input.
- Counters are updated after **each** certificate, so polling a large job shows live progress.
- Timestamps are UTC.

**Job statuses**

| Status | Meaning |
|---|---|
| `pending` | Accepted, generation not started yet |
| `processing` | The worker is generating certificates |
| `completed` | Every certificate succeeded |
| `completed_with_errors` | Some succeeded, some failed |
| `failed` | Nothing succeeded (includes a job where every row was invalid) |

**Certificate statuses:** `pending`, `success`, `failed`.

## 6. Retrieve generated certificates

**One certificate (PDF)**, using the `download_url` from the job status:

```bash
curl -o asha.pdf http://localhost:8000/certificates/<certificate-id>/download
```

**All successful certificates of a job (ZIP):**

```bash
curl -o certificates.zip http://localhost:8000/jobs/<job-id>/download
```

Files inside the ZIP are named `<row number>_<name>.pdf`, e.g. `0001_Asha_Verma.pdf`,
`0003_Meera_Iyer.pdf`. Failed rows are not included.

**Error responses**

| Situation | Status |
|---|---|
| Unknown job or certificate id | `404` |
| Certificate exists but failed / is not ready | `409` |
| Job ZIP requested while the job is still `pending`/`processing` | `409` |
| Job has no successful certificates | `404` |

## 7. API reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/jobs` | Create a bulk job → `202` with job id |
| `GET` | `/jobs/{job_id}` | Status, progress and per-recipient results |
| `GET` | `/jobs/{job_id}/download` | ZIP of all successful certificates |
| `GET` | `/certificates/{certificate_id}/download` | One certificate PDF |
| `GET` | `/health` | Liveness check |

## 8. Configuration

Set as environment variables or in a `.env` file at the project root (real environment
variables win over `.env`). All are optional.

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL |
| `GENERATED_DIR` | `<project>/generated` | Where PDFs and ZIPs are written |
| `TEMPLATE_DIR` | `<project>/templates` | Folder containing `certificate_template.json` |
| `MAX_RECIPIENTS_PER_JOB` | `5000` | Largest accepted request |

## 9. Design decisions

### Background processing (instead of synchronous)

`POST /jobs` stores the job and returns `202` straight away; FastAPI's `BackgroundTasks`
then generates the certificates in the same process, and the client polls `GET /jobs/{id}`.

*Why not synchronous?* A request with thousands of recipients would hold an HTTP
connection open for as long as it takes to render every PDF, risking client/proxy
timeouts, and the client would learn nothing until the very end. The brief also asks for
progress tracking, which only makes sense if the work happens after the response.

*Why not Celery/RQ?* They are the right tool at larger scale (see
[limitations](#11-known-limitations-and-next-steps)), but they add a broker (Redis),
a separate worker process and more deployment to a project whose scale does not need
them. `BackgroundTasks` has no extra infrastructure, and the worker logic is isolated
in `app/workers.py` (`process_job(job_id)`), so moving it to a real queue means
changing one line in the route.

### Validation happens at two levels

- **Request level** (Pydantic, `422`): problems that make the whole request meaningless,
  such as missing course name, empty recipient list or too many recipients.
- **Row level** (`job_service.create_job`): each recipient is validated on its own.
  `recipients` is deliberately typed as a loose `list[dict]` in the request schema; if it
  were a strictly typed list, one bad row would reject all the others with a `422`.
  Instead a bad row is stored as a `failed` certificate with a readable error and is
  never sent to the worker.

### Failure isolation

The worker wraps **each certificate** in its own `try/except`. Any exception (bad
data, rendering error, disk error) marks only that certificate `failed`, stores the error
message, and the loop continues. The job's final status is derived from the counters.
If something unexpected kills the worker itself, a fallback marks the remaining
certificates failed and closes the job so it is never left stuck in `processing`.

### Progress tracking

`Job` stores `total`, `succeeded` and `failed`. The worker commits after every certificate,
so progress is visible while the job runs. The trade-off is one commit per certificate,
which is fine at this scale; batching commits (e.g. every 50) is the first optimisation if
it ever matters.

### Data model

Two tables: `jobs` (certificate info, status, counters, timestamps) and `certificates`
(one row per recipient: row index, name, email, status, file path, error message), related
one-to-many with cascade delete. IDs are UUIDs, so URLs are not guessable sequential numbers.
Name and email are nullable on `certificates` because an invalid row may not have them.

### Certificate template

There is a single predefined template, split in two:

- `templates/certificate_template.json`: wording and colours (title, labels, date format).
- `app/services/generator_service.py`: layout (landscape A4, border, positions) drawn
  with ReportLab.

Each PDF is written to a temporary file and renamed on success, so a failure never leaves
a half-written certificate. Long names are shrunk to fit; names that still cannot fit
fail cleanly for that recipient.

### Layered structure

`routes` (HTTP only) → `services` (business logic) → `db` (models/session).
The generator is isolated from the job logic, which is what makes it easy to replace
with a fake in tests to force a failure.

### SQLite

SQLite is a relational database and needs no setup, so the project runs with zero
infrastructure. Everything goes through SQLAlchemy, so pointing `DATABASE_URL` at
PostgreSQL requires no code changes (the PostgreSQL driver must be installed, and this
path is not covered by the test suite, which uses SQLite).

## 10. Deployment to AWS EC2

Pushing to `main` runs the tests; if they pass, GitHub Actions connects to the EC2 server
over SSH, pulls the new code and restarts the app with Docker Compose.

```
git push → CI (pytest) ✔ → deploy.yml → SSH to EC2 → git pull → docker compose up --build → health check
                                                                      └─ on failure: roll back to the previous commit
```

### One-time server setup (Ubuntu 22.04 / 24.04)

1. **Launch the instance.** `t3.small` or larger, Ubuntu. Security group: port **22** (only your IP),
   **80** and **443** (anywhere). Attach an **Elastic IP** so the address never changes.
2. **Let the server read the repo.** On the server create a read-only *deploy key* and add it
   in GitHub under *Repo → Settings → Deploy keys*:
   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""
   cat ~/.ssh/id_ed25519.pub        # paste this into GitHub
   ssh -T git@github.com            # should greet you by repo name
   ```
3. **Prepare the server** (installs Docker, nginx, clones the repo to `/opt/bulk-certificate-generator`):
   ```bash
   git clone git@github.com:<you>/bulk-certificate-generator.git /tmp/bcg
   bash /tmp/bcg/devops/scripts/setup_ec2.sh git@github.com:<you>/bulk-certificate-generator.git
   ```
   Log out and back in (so the `docker` group applies), then do the first start:
   ```bash
   cd /opt/bulk-certificate-generator && bash devops/scripts/deploy.sh
   curl http://localhost/health      # {"status":"ok"}
   ```
4. **Create a deploy SSH key for GitHub Actions** (on your own machine) and authorise it on the server:
   ```bash
   ssh-keygen -t ed25519 -f deploy_key -N ""
   # append deploy_key.pub to ~/.ssh/authorized_keys on the server
   ```
5. **Add GitHub secrets** (*Repo → Settings → Secrets and variables → Actions*):

   | Secret | Value |
   |---|---|
   | `EC2_HOST` | the Elastic IP or domain name |
   | `EC2_USER` | `ubuntu` |
   | `EC2_SSH_KEY` | the full contents of the **private** key `deploy_key` |
   | `EC2_PORT` | optional, only if SSH is not on 22 |

From now on every push to `main` deploys automatically. You can also run it by hand from the
**Actions → Deploy to EC2 → Run workflow** button. Check the result at `http://<EC2_HOST>/health`
and `http://<EC2_HOST>/docs`.

### HTTPS and a domain

Point a DNS `A` record at the Elastic IP, put the domain in `server_name` in
`devops/nginx/default.conf`, then on the server:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain
```

### Things to know

- **Data survives deploys.** The database and PDFs live in the `certificate_data` Docker volume,
  which `docker compose up` does not touch.
- **A deploy restarts the container**, so a job that is running at that moment is left in
  `processing` (see limitations). Deploy when no large job is running.
- **No database migrations.** Tables are created with `create_all`, which never alters existing
  tables. If you change a model's columns, the live database needs a manual change or a reset
  (`docker compose down -v` deletes all data). Alembic would be the proper fix.
- **Rollback** is automatic if the new version fails its health check (up to 60 s), by redeploying
  the previous commit.
- Port `8000` is also published by `docker-compose.yml`. For a stricter setup, close it in the
  security group (nginx on port 80 is the intended entry point).

## 11. Known limitations and next steps

- **A server restart mid-job leaves that job in `processing`.** `BackgroundTasks` lives in
  the web process. The worker is idempotent (re-running a job only handles still-`pending`
  certificates, and this is tested), so a startup task that re-queues stuck jobs would fix
  it; a persistent queue (Celery/RQ/ARQ) would fix it properly and allow scaling workers
  independently of the API.
- **Latin characters only.** The built-in PDF fonts cannot render e.g. Devanagari or
  Chinese names. Such recipients fail with a clear error instead of producing a garbled
  PDF. Supporting them means registering a Unicode TTF font (such as Noto Sans) in
  `generator_service.py`.
- **No authentication or rate limiting**, and certificates are stored on local disk.
  A real deployment would add auth, and object storage (S3) for files.
- **No idempotency key.** Submitting the same request twice creates two jobs.
- **The job ZIP is rebuilt on each download.** Fine for thousands of files; for much larger
  jobs it could be built once by the worker, or streamed.
- **No sending of certificates by email**, and no retry endpoint for failed rows
  (the client can resubmit just the failed rows as a new job).

## 12. Project structure

```
bulk-certificate-generator/
├── app/
│   ├── main.py                      # FastAPI app, startup, routers
│   ├── workers.py                   # background task: loops recipients, isolates failures
│   ├── api/
│   │   ├── deps.py                  # DB session dependency
│   │   └── routes/
│   │       ├── jobs.py              # POST /jobs, GET /jobs/{id}, GET /jobs/{id}/download
│   │       └── certificates.py      # GET /certificates/{id}/download
│   ├── core/config.py               # settings from env / .env
│   ├── db/
│   │   ├── database.py              # engine, session factory, table creation
│   │   └── models.py                # Job, Certificate
│   ├── schemas/                     # Pydantic request/response models
│   └── services/
│       ├── job_service.py           # create job (per-row validation), status transitions
│       ├── certificate_service.py   # lookup, file paths, ZIP
│       └── generator_service.py     # renders ONE PDF
├── templates/certificate_template.json
├── generated/                       # output (git-ignored, only .gitkeep is tracked)
├── tests/
│   ├── conftest.py                  # in-memory DB, temp output dir, client, factories
│   ├── unit/                        # models, schemas, services, worker
│   └── api/                         # endpoints end to end
├── docker/                          # Dockerfile + Dockerfile.dockerignore
├── devops/
│   ├── scripts/
│   │   ├── setup_ec2.sh             # one-time server preparation
│   │   ├── deploy.sh                # rebuild + restart + health check (runs on the server)
│   │   └── health_check.sh          # waits for GET /health
│   └── nginx/default.conf           # port 80 -> app
├── .github/workflows/
│   ├── ci.yml                       # runs pytest on push / PR
│   └── deploy.yml                   # after CI passes on main: deploy to EC2 over SSH
├── docker-compose.yml
├── pytest.ini
├── requirements.txt                 # runtime dependencies
├── requirements-dev.txt             # + pytest, httpx
└── .env.example
```