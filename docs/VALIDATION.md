# Release validation — 2026-11-03

This record describes checks actually run during the 0.2.0 implementation.

| Check | Result |
| --- | --- |
| Python 3.11 backend tests | 33 passed |
| Backend lint | Ruff passed |
| Next.js production compilation | Passed, including TypeScript |
| Authenticated browser suite | 4 passed: sign-in/sign-out, dashboard/catalog, drawing overlays/reports, mobile layout |
| Live API + worker + genuine EasyOCR smoke test | Passed: PDF upload, three annotations, three material findings, rendered image, PDF and CSV |
| Database migrations | Fresh upgrade and populated-catalog upgrade checked; Alembic reports no schema drift |
| Python environment audit | No known vulnerabilities reported by pip-audit |
| Frontend dependency audit | npm audit reported zero vulnerabilities |

## Synthetic OCR fixture

The fixture is generated in `backend/scripts/evaluate.py` using three clean English annotations:

- ASBESTOS CEMENT BOARD
- VINYL FLOOR TILE
- GLASS WOOL INSULATION

Both EasyOCR 1.7.2 and PaddleOCR 3.7.0 recognized all three annotations exactly on CPU. Character error rate and word error rate were both 0 for this fixture. EasyOCR mean confidence was approximately 0.753; PaddleOCR mean confidence was approximately 0.9998. Different model confidence scores are not calibrated against one another.

The demonstration catalog remains unverified/UNKNOWN, so the live application correctly routed every fixture material to manual review despite high similarity or high OCR confidence.

The matching evaluation script reports precision, recall, F1, and an actual-versus-predicted confusion matrix over seven synthetic rule cases. It uses an isolated in-memory catalog and makes no real product claims.

## Practical limits

These results validate implementation behavior on synthetic data. They do not measure performance on real engineering drawings, degraded scans, Japanese material descriptions, or laboratory-verified asbestos samples.

SQLite was used for local integration tests. PostgreSQL configuration is provided but has not been exercised against a live PostgreSQL server here. Docker was unavailable locally; container builds and a full-stack container smoke/browser workflow are configured in GitHub Actions.

A public deployment still needs its own hostname, HTTPS termination, configured credentials, reference data, backup/restore validation, and capacity testing.

