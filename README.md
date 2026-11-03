# Engineering Drawing Intelligence

An end-to-end starter for traceable OCR and asbestos-material review.

## Run locally

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API accepts PDF/PNG/JPG/JPEG uploads at `POST /api/documents`. It uses PyMuPDF and OpenCV when installed, and keeps uncertain matches in `MANUAL_REVIEW`.

The frontend can be run with Node.js:

```bash
cd frontend && npm install && npm run dev
```
