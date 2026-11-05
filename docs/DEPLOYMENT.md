# Deployment and operations

This release supports one authenticated review workspace and one dispatcher per database/upload directory. It is suitable for a private team or portfolio deployment behind HTTPS. Individual accounts, tenant isolation, and horizontal worker scaling require additional architecture.

## Local development

Use Python 3.11 and Node.js 22. The supervised native launcher uses a separate
virtual environment, database, uploads, and model cache under
`~/.local/share/ed-native`; it does not reuse `backend/.venv` or `backend/ed.db`.
From the repository root:

```bash
python3.11 scripts/local.py setup --provision-models
python3.11 scripts/local.py run
```

Put Node.js 22 and npm on PATH first. On this workstation:

```bash
export PATH="$HOME/.local/share/invoicelens-tools/node-v22.23.4-darwin-arm64/bin:$PATH"
"$HOME/.local/share/uv/python/cpython-3.11.18-macos-aarch64-none/bin/python3.11" scripts/local.py setup --provision-models
"$HOME/.local/share/uv/python/cpython-3.11.18-macos-aarch64-none/bin/python3.11" scripts/local.py run --api-port 8010 --web-port 3010
```

`setup` installs the hash-verified base lock, the pinned EasyOCR profile constrained
to that lock, and frontend dependencies using `npm ci`. OCR transitive dependencies
outside the base lock are resolved at install time. `--provision-models` downloads
weights into the isolated model cache. Use `--state-dir /absolute/path` on both
commands for a different workspace. `run` checks ports before migrations, starts
API/worker/frontend, and stops its own child process groups on Ctrl-C or a child
failure. It refuses occupied ports and a second launcher using the same state.
It never terminates unrelated processes. Default URLs are http://localhost:3000
and http://127.0.0.1:8000; choose alternate ports when an existing stack is live.
Configuration still reads `backend/.env`; database, uploads, model cache, CORS,
and frontend API target are overridden to the isolated workspace.

For manual development, use a Python 3.11 environment, install
`requirements.lock` with `--require-hashes`, then install `requirements-dev.txt`
and `requirements-easyocr.txt` with `-c requirements.lock`. Run migrations before
starting `uvicorn app.main:app` and `python -m app.worker` in separate terminals.
Requests use a same-origin frontend proxy; `API_INTERNAL_URL` must be set before
building if the backend is hosted elsewhere. Uploads remain queued until the
worker is running.

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

The shared dependency lock keeps NumPy below 2.4 and PyYAML at 6.0.2 for
PaddleX 3.7 compatibility. Optional OCR installs are constrained to that lock;
`pip check` verifies the final image dependency graph. Paddle's optional profile
resolves for Linux x86_64; a local Docker build and genuine Paddle inference have
not been verified on this workstation. PaddleX also installs an OpenCV contrib
distribution alongside the application's headless OpenCV; validate the resulting
`cv2` runtime on the target image before using Paddle in production.

Both engines use CPU by default. The installed PaddleOCR version chooses its default detection and recognition models; model downloads require network access during provisioning. Preserve model volumes and test initialization before operating offline.

## Private deployment

Use the production override explicitly. Compose requires `AUTH_PASSWORD` and
`PUBLIC_ORIGIN` before it can render the configuration; application startup also
validates the password, username, and explicit HTTPS origins. Values in this
override take precedence over `backend/.env` for migration, API, and worker.
Keep `backend/.env` present for the base Compose environment file.

```bash
# Configure an HTTPS proxy and DNS for this hostname first.
export PUBLIC_ORIGIN=https://drawings.example.com
export AUTH_USERNAME=reviewer
read -r -s -p 'Production password (at least 16 characters): ' AUTH_PASSWORD; echo
export AUTH_PASSWORD
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.production.yml up --build -d --wait
docker compose -f docker-compose.yml -f docker-compose.production.yml exec -T backend python scripts/provision_models.py --engine easyocr
unset AUTH_PASSWORD
```

The password prompt above uses Bash. For repeat operations, supply the same
variables through your deployment secret store or a private root `.env` file
(which Git ignores). Avoid printing the resolved Compose configuration because
it includes credentials. Use the same two `-f` flags and secrets for subsequent
production Compose commands. `PUBLIC_ORIGIN` is an origin such as
`https://drawings.example.com`, without paths or wildcards. A single deployment
supports one configured reviewer identity and one dispatcher.

The browser presents a sign-in form. Successful login creates an HttpOnly,
SameSite=Strict session cookie with an eight-hour lifetime; production cookies
are Secure and require HTTPS. Password changes invalidate existing sessions.
HTTP Basic remains available for API clients.

Signing out persists a hash of the revoked session token, so copied cookies
cannot be replayed after logout or an API restart. Apply migrations before
starting this version; the latest revision is `a41f8f92c201`.

Terminate TLS at your existing reverse proxy and forward to 127.0.0.1:3000.
For example, adapt this nginx server block to a hostname and certificate you own:

```nginx
server {
    listen 443 ssl;
    server_name drawings.example.com;
    ssl_certificate /etc/letsencrypt/live/drawings.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/drawings.example.com/privkey.pem;
    client_max_body_size 55m; # default MAX_UPLOAD_MB=50 plus multipart overhead
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

This proxy example does not provision certificates. Increase the request-body
limit if you raise `MAX_UPLOAD_MB`; restrict public access to the TLS proxy.
The default Compose file remains a localhost development configuration.

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

- API health: GET /api/health validates database access. This is an API liveness check.
- GET /api/ready checks database access and a worker heartbeat less than 15 seconds old. It does not establish model readiness.
- Compose checks the worker heartbeat file every five seconds, with a 30-second startup grace period. A stale worker is unhealthy; Docker restart policy alone does not restart unhealthy containers.
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

