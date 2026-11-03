"""Download and initialize configured OCR weights before accepting drawing jobs."""

import argparse
from app.services.ocr import reader
from app.core.config import settings

parser = argparse.ArgumentParser()
parser.add_argument("--engine", choices=["easyocr", "paddleocr"], default="easyocr")
args = parser.parse_args()
reader(args.engine, tuple(settings.ocr_languages.split(",")))
print(f"{args.engine} initialized successfully")
