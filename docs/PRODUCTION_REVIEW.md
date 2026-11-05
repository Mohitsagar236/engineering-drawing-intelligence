# Production review — 2026-11-05

Reviewed the backend API, authentication, schema and migrations, upload parsing,
OCR and matching, dispatcher, reports, frontend flows, styles, browser tests,
dependency profiles, containers, CI, and operating instructions. The supported
deployment remains one authenticated workspace with one API process and one
dispatcher sharing a database and upload directory.

## Completed fixes

| Area | Problem resolved |
| --- | --- |
| Authentication | Persisted logout revocations prevent replaying a copied cookie. A new migration adds the revocation table. Failed Basic authentication and invalid login payloads are throttled, with a retry interval. |
| Request handling | Login bodies are capped at 16 KiB and other JSON writes at 64 KiB before parsing. Validation errors no longer echo rejected credentials. Error responses receive request IDs and no-store/security headers. |
| Configuration | Production requires credentials and explicit HTTPS origins; wildcard origins are rejected. Image pixel limits are bounded. |
| Uploads | Image/PDF content must match the declared filename extension. Missing original files return a recoverable conflict when reprocessing. |
| Worker | Heartbeats support `/api/ready` and container health checks. Shutdown and timeout terminate and reap inference; an orphan monitor handles dispatcher death. Interrupted jobs receive completion timestamps. Stale inference cannot publish a completed result after its job has failed. |
| Evidence | Whitespace is rejected in material names and review evidence. Reviews require a completed analysis. Nonfinite OCR scores are rejected. Japanese hazard/material terms remain visible for manual review even without a catalog match. |
| Database | Document listing, findings/reviews, dashboard counts, catalog imports, and per-analysis material matching avoid repeated per-record catalog/database queries. Each analysis retains one consistent reference catalog snapshot. |
| CSV | Empty or malformed headers and duplicate names are rejected. Imports report inserted and skipped records accurately. Exports escape formulas even after leading whitespace. |
| Frontend | All document pages are accessible. Stale requests cannot overwrite another view; polling preserves page and zoom. Session expiry clears the workspace. Requests have timeouts and readable retry errors. Review drafts are isolated by finding. Catalog search and import counts are available. |
| Deployment | Shared dependency bounds resolve the optional Paddle profile conflict. Hash lock, dependency consistency checks, worker health checks, an explicit production Compose override, and an isolated native launcher are included. |

## Verification performed

- Python 3.11 isolated environment using the updated dependency lock and EasyOCR
  profile: all 70 backend tests and Ruff passed (33 tests before this review).
- Next.js optimized production build, TypeScript, frontend formatting, and
  whitespace checks passed.
- The authenticated browser suite passed all 13 tests during the frontend review.
  The final local rerun passed 12 tests, with the authenticated sign-out test
  skipped because the local workspace runs without a password. Backend tests
  separately cover login, logout, copied-token revocation, and throttling.
- Genuine EasyOCR smoke passed on the updated running API and dispatcher: three
  recognized annotations, three material findings routed to manual review,
  rendered page, PDF report, and CSV report.
- Fresh database migration and schema drift check passed. The existing local
  database was backed up and upgraded to `a41f8f92c201`; no schema drift remains.
- `pip check` passed; `pip-audit` and `npm audit` reported no known vulnerabilities.
- All seven synthetic classification-rule cases passed the matching evaluation.
- Frontend returns HTTP 200; proxied `/api/ready` reports database and worker ready.

The live-review browser regression now reopens a drawing by its ID, so two
different uploads with the same filename cannot invalidate its persistence check.
Synthetic smoke/browser fixtures were added to the local workspace during testing.
A pre-upgrade database backup was retained outside the repository. This is a
temporary local backup, not a deployment retention policy.

### Follow-up: upload proxy and icon

An upload above 10 MiB exposed Next.js request-body truncation that the original
small smoke fixtures did not exercise. The frontend proxy now buffers up to the
API's 200 MiB configuration ceiling plus multipart overhead, and its timeout is
aligned to the upload timeout. The API still enforces the configured file-size
limit (50 MiB by default); the browser also checks that limit before sending.
A live browser regression uploads a valid uncompressed PNG of approximately
12 MiB through the frontend and requires HTTP 202. Application SVG metadata and
a `/favicon.ico` redirect eliminate the missing favicon. The production build
and all 15 applicable browser tests passed; the authenticated sign-out test
remains skipped in the local password-free configuration.

### Follow-up: false material matches in a non-drawing document

A two-page academic document exposed false material detections that the earlier
synthetic material-only fixture did not cover. Weighted substring similarity
gave short grades a high score against material aliases, and unrelated headings
were presented under a candidate's material name. Replaying the saved 275 OCR
annotations under the corrected rules reduced 16 false material candidates to
zero.

`material-reference-v2` compares complete names, requires a minimum fuzzy score
of 0.85, excludes short/numeric fragments from fuzzy matching, and rejects fuzzy
identity suggestions for very low-confidence OCR. Exact abbreviations remain
supported. Fuzzy annotations retain their source text and label the reference as
a suggestion. Conflicting exact aliases do not select an arbitrary product.
New runs record the matching-rules version; historical evidence is unchanged.

The viewer now offers searchable **All extracted text** alongside material
findings. Non-material OCR rows use a neutral label rather than an asbestos
review status. Overlays follow the selected view/search, and model confidence
is explicitly distinguished from measured accuracy.

Verification: 89 backend tests, 17 browser tests, production build, formatting,
lint, and the existing synthetic classification evaluation passed. One browser
sign-out test is skipped under local password-free configuration. Reprocessing
the actual document completed as analysis 7: all 275 OCR annotations were
retained, with zero material findings. A live browser check confirmed the empty
material view, searchable raw-text view, neutral annotation labels, and source
text inspection. The original analysis remains available in history.

A separate small-text OCR experiment increased detected text slightly but did
not recover the grade table reliably. It was not adopted as an accuracy fix.
Dense scan/table recognition and structured academic-document extraction remain
limitations; there is no claim of fully accurate transcript parsing.

## Deployment acceptance still required

These are deployment-specific checks, not claims of completed validation:

- Configure the real hostname, TLS certificates/proxy, credentials, and verified
  reference catalog using [DEPLOYMENT.md](DEPLOYMENT.md).
- Run container builds and the full stack on the target host. Docker is not
  installed on this workstation; CI contains the container validation workflow,
  but that workflow has not been run remotely in this task.
- Optional PaddleOCR inference is not validated here. Its Linux dependency
  profile resolves, but the final OpenCV/runtime combination needs target-image
  verification before enabling Paddle in production.
- PostgreSQL, coordinated backup/restore drills, realistic load/capacity, and
  field/Japanese OCR accuracy need testing against the intended infrastructure
  and drawings. Synthetic fixtures do not establish field accuracy.

The application is running locally with a production-built frontend and the
updated Python 3.11 API/worker. Local authentication remains disabled under the
development configuration; the production override enforces authentication.
