# Engineering Drawing Intelligence

AI-assisted OCR and material-risk review for architectural and structural engineering drawings.

The application turns uploaded plans, elevations, specifications, and scanned drawings into traceable material findings. Each finding retains its source text, page number, OCR confidence, engine, and bounding-box coordinates for review against the original drawing.

> **Safety first:** OCR uncertainty and database mismatches are never treated as proof of non-asbestos. Unless a verified reference record supports the decision, the result remains `MANUAL_REVIEW`.

## Current capabilities

- Upload PDF, PNG, JPG, and JPEG drawings
- Render PDF pages for page-level processing
- OpenCV preprocessing foundation for scanned drawings
- Pluggable PaddleOCR and EasyOCR adapters
- Preserve OCR confidence, engine, page, and bounding-box data
- Normalize material names and match them against a reference catalog
- SQLite persistence through SQLAlchemy
- Safety-aware asbestos classifications
- Downloadable analysis reports
- Next.js upload and workspace dashboard

## Architecture

```text
Next.js dashboard → FastAPI REST API → SQLAlchemy / SQLite
                              ├─ PDF and image extraction
                              ├─ OpenCV preprocessing
                              ├─ PaddleOCR / EasyOCR adapters
                              └─ material normalization and safety matching
```

## Repository layout

```text
ED/
├── backend/app/
│   ├── core/       # Environment configuration
│   ├── db/         # Database session
│   ├── models/     # SQLAlchemy models
│   ├── schemas/    # Pydantic schemas
│   └── services/   # OCR and material matching
├── frontend/app/   # Next.js interface
└── README.md
```

## Run locally

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

API: `http://localhost:8000` · Swagger docs: `http://localhost:8000/docs`

### Frontend

In a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`.

## API quick reference

```bash
# Upload a drawing
curl -X POST http://localhost:8000/api/documents -F "file=@path/to/drawing.pdf"

# List analyses
curl http://localhost:8000/api/documents

# Download a report
curl -OJ http://localhost:8000/api/documents/1/report
```

## Classification behavior

| Result | Meaning |
|---|---|
| `ASBESTOS_CONTAINING` | A verified reference record explicitly supports asbestos presence. |
| `NON_ASBESTOS` | A verified reference record explicitly supports non-asbestos status. |
| `MANUAL_REVIEW` | The match is uncertain, conditional, unknown, or below threshold. |

Condition-dependent materials remain in manual review until the applicable conditions are verified.

## Configuration

Optional `backend/.env` values:

```env
DATABASE_URL=sqlite:///./ed.db
UPLOAD_DIR=./uploads
MAX_UPLOAD_MB=50
OCR_ENGINE=auto
```

SQLite is the default for local development. The SQLAlchemy architecture is compatible with PostgreSQL deployment.

## Roadmap

- Store rendered page images and show OCR overlays in the viewer
- Add asynchronous processing and upload progress events
- Add configurable preprocessing profiles and OCR comparison
- Expand the material catalog with source and verification metadata
- Add PostgreSQL, object storage, Docker Compose, tests, and CI

## Disclaimer

This project is an engineering-review aid, not a substitute for certified asbestos surveying, laboratory analysis, regulatory interpretation, or professional approval. Findings must be independently verified before remediation, demolition, procurement, or compliance decisions.
