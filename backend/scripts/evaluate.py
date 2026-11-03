"""Reproducible synthetic OCR evaluation. Never represents field accuracy."""

import argparse
import json
from pathlib import Path
import pymupdf as fitz
from PIL import Image
from app.services.ocr import recognize_image

TEXTS = ["ASBESTOS CEMENT BOARD", "VINYL FLOOR TILE", "GLASS WOOL INSULATION"]


def distance(a, b):
    previous = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        current = [i]
        for j, right in enumerate(b, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (left != right))
            )
        previous = current
    return previous[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", choices=["easyocr", "paddleocr"], default="easyocr")
    parser.add_argument("--output", default="")
    args = parser.parse_args()
    with fitz.open() as document:
        page = document.new_page(width=700, height=400)
        for i, text in enumerate(TEXTS):
            page.insert_text((40, 80 + i * 100), text, fontsize=24)
        pix = page.get_pixmap(dpi=150, alpha=False)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    rows = recognize_image(image, args.engine, {})
    expected = " ".join(TEXTS).casefold()
    actual = " ".join(r[0] for r in rows).casefold()
    report = {
        "dataset": "synthetic-clean-english-v1",
        "engine": args.engine,
        "expected": expected,
        "recognized": actual,
        "cer": distance(expected, actual) / len(expected),
        "wer": distance(expected.split(), actual.split()) / len(expected.split()),
        "annotations": len(rows),
        "mean_ocr_confidence": sum(r[1] for r in rows) / max(1, len(rows)),
        "limitation": "One clean synthetic drawing; not a real-world accuracy estimate.",
    }
    print(json.dumps(report, indent=2))
    if args.output:
        Path(args.output).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
