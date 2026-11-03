# Deployment and operations

This release supports one authenticated review workspace and one dispatcher per database/upload directory. It is suitable for a private team or portfolio deployment behind HTTPS. Individual accounts, tenant isolation, and horizontal worker scaling require additional architecture.

## Local development

Use Python 3.11 and Node.js 22. From the repository root:

```bash
python3.11 -m venv backend/.venv
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
pip install -r requirements-easyocr.txt
cp .env.example .env
alembic upgrade head
PYTHONPATH=. python scripts/provision_models.py --engine easyocr
uvicorn app.main:app --reload
```

Start the dispatcher in another terminal using the same environment and working directory:

```bash
cd backend
source .venv/bin/activate
python -m app.worker
```

Start the frontend in a third terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000. Requests use a same-origin API proxy; set `API_INTERNAL_URL` before building if the backend is hosted elsewhere. Uploads remain queued until the dispatcher is running.

## Containers

```bash
cp backend/.env.example backend/.env
docker compose up --build -d
docker compose run --rm backend python scripts/provision_models.py --engine easyocr
```

The web application is bound to 127.0.0.1:3000. API port 8000 is internal. Docker Compose runs migrations before the API starts and starts the worker after the API becomes healthy. Persistent volumes store the catalog, uploads, rendered pages, and model weights.

The frontend container runs a compiled Next.js standalone server, and backend containers run as an unprivileged user. Inference runs in a child process with a configured timeout. Worker shutdown terminates in-flight inference; interrupted analyses can be retried while retaining their history.

For PaddleOCR, set `INSTALL_PADDLE=true` in the shell before building:

```bash
INSTALL_PADDLE=true docker compose build
INSTALL_PADDLE=true docker compose up -d
docker compose run --rm backend python scripts/provision_models.py --engine paddleocr
```

Both engines use CPU by default. The installed PaddleOCR version chooses its default detection and recognition models; model downloads require network access during provisioning. Preserve model volumes and test initialization before operating offline.

## Private deployment

Set these values in `backend/.env`:

```env
ENVIRONMENT=production
AUTH_USERNAME=reviewer
AUTH_PASSWORD=<a randomly generated secret of at least 16 characters>
CORS_ORIGINS=https://drawings.example.com
```

Production startup rejects a missing or short password. The browser presents a sign-in form. Successful login creates an HttpOnly, SameSite=Strict session cookie with an eight-hour lifetime; in production the cookie is Secure and requires HTTPS. Passwords are never stored in browser local storage. Changing the configured password invalidates existing sessions. HTTP Basic remains available for API clients. All authenticated users share the configured reviewer identity.

Terminate TLS at your existing reverse proxy and forward to 127.0.0.1:3000. Set the proxy request-body limit to at least MAX_UPLOAD_MB plus multipart overhead. Restrict external access to the proxy. Credentials belong in a deployment secret store or private environment file.

## Database and schema

SQLite is the default. Stop API and worker writes before taking a coordinated snapshot of the database and upload volumes; keep all three SQLite files together if using filesystem snapshots while WAL is active. A consistent SQLite backup can also use the SQLite backup API. Test restoration in a separate environment.

For PostgreSQL use a `postgresql+psycopg://...` DATABASE_URL and remove the SQLite URL override in Compose. API and worker must use the same database and shared upload storage. Run:

```bash
alembic upgrade head
alembic check
```

Migrations are versioned under backend/migrations. Production startup does not create schema automatically. The initial migration targets a new database; archive any database from the early scaffold before upgrading. That scaffold did not retain original upload-to-document paths, so historical jobs cannot be reconstructed automatically.

## Review and reference records

Seed records are explicitly demonstration data with UNKNOWN status. CSV imports always become UNVERIFIED. Verify references individually using a documented product-specific source. Conditional references remain in manual review. Fuzzy similarity is a candidate suggestion and cannot establish asbestos status.

A manual review requires a reason and evidence source. Review decisions are appended to audit history; the original AI classification and reference snapshot remain available. Existing findings are not rewritten when the catalog changes: rerun an analysis to use new reference records.

## Recovery, retention, and diagnostics

- API health: GET /api/health validates database access. This is an API liveness check, not proof of worker or model readiness.
- Queue state, failures, and analysis history are visible in the dashboard and document views.
- Use `docker compose logs -f backend worker` for server and inference failures.
- Failed or interrupted analyses can be retried using Run analysis; a new job preserves the earlier run.
- Run exactly one dispatcher. A file lock prevents two dispatchers from consuming the same upload directory.
- Configure PROCESSING_TIMEOUT, MAX_PAGES, MAX_IMAGE_PIXELS, and RENDER_DPI for available RAM.
- Uploads and rendered pages are retained until an operator archives them. Back up database and files together; no automated retention deletion is enabled.
- To restore, stop services, restore the matching database/files/model volumes, run migrations, then start API and worker.

## Verification commands

```bash
cd backend
PYTHONPATH=. pytest -q tests
ruff check app tests scripts
alembic check
pip-audit
PYTHONPATH=. python scripts/evaluate.py --engine easyocr
PYTHONPATH=. python scripts/evaluate.py --engine paddleocr
PYTHONPATH=. python scripts/evaluate_matching.py
python scripts/smoke.py
```

The smoke test requires a running API and worker. It creates a synthetic drawing and verifies genuine OCR, manual-review handling, page rendering, and report exports. Browser tests require the running stack plus that synthetic drawing:

```bash
cd frontend
npm ci
npm run build
npx playwright install chromium
npx playwright test
```

CI validates backend tests, migrations, frontend compilation, dependency audits, and container build definitions. Field accuracy, Japanese recognition quality, restoration drills, and load capacity must be measured on the deployment's own drawings and hardware.

