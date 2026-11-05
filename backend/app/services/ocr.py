import importlib.util
import io
import logging
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
from PIL import Image, ImageOps
from app.core.config import settings

logger = logging.getLogger(__name__)
Image.MAX_IMAGE_PIXELS = settings.max_image_pixels


def inspect_file(path):
    if Path(path).suffix.lower() == ".pdf":
        import pymupdf as fitz

        with fitz.open(path) as doc:
            if (
                not doc.is_pdf
                or doc.needs_pass
                or not 1 <= len(doc) <= settings.max_pages
            ):
                raise ValueError(
                    "PDF must be unencrypted and within the configured page limit"
                )
            for page in doc:
                if (
                    page.rect.width * page.rect.height * (settings.render_dpi / 72) ** 2
                    > settings.max_image_pixels
                ):
                    raise ValueError("PDF page exceeds rendering pixel limit")
            return len(doc)
    with Image.open(path) as image:
        expected = "PNG" if Path(path).suffix.lower() == ".png" else "JPEG"
        if (
            image.format != expected
            or image.width * image.height > settings.max_image_pixels
        ):
            raise ValueError("Unsupported image content or image exceeds pixel limit")
        image.verify()
    return 1


def iter_pages(path):
    if Path(path).suffix.lower() == ".pdf":
        import pymupdf as fitz

        with fitz.open(path) as doc:
            for page in doc:
                pix = page.get_pixmap(dpi=settings.render_dpi, alpha=False)
                yield Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    else:
        with Image.open(path) as image:
            yield ImageOps.exif_transpose(image).convert("RGB")


def pages_for_file(path):
    inspect_file(path)
    for image in iter_pages(path):
        stream = io.BytesIO()
        image.save(stream, format="PNG")
        yield stream.getvalue()


def preprocess(image, config):
    # These operations preserve dimensions; boxes remain in rendered-page coordinates.
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    if config.get("denoise"):
        gray = cv2.fastNlMeansDenoising(gray, h=10)
    if config.get("contrast"):
        gray = cv2.createCLAHE(clipLimit=2, tileGridSize=(8, 8)).apply(gray)
    if config.get("threshold"):
        gray = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11
        )
    return gray


def available_engines():
    return {
        name: importlib.util.find_spec(module) is not None
        for name, module in (("easyocr", "easyocr"), ("paddleocr", "paddleocr"))
    }


@lru_cache(maxsize=2)
def reader(engine, languages):
    if engine == "easyocr":
        import easyocr

        return easyocr.Reader(list(languages), gpu=False, verbose=False)
    from paddleocr import PaddleOCR

    if len(languages) != 1:
        raise ValueError("PaddleOCR requires one model language; select en or japan")
    lang = "japan" if languages[0] == "ja" else languages[0]
    return PaddleOCR(
        lang=lang,
        device="cpu",
        use_doc_orientation_classify=False,
        use_doc_unwarping=False,
        use_textline_orientation=False,
    )


def polygon(box):
    array = np.asarray(box, dtype=float)
    if array.size == 4:
        x1, y1, x2, y2 = array.reshape(-1)
        array = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])
    points = array.reshape(-1, 2)
    if len(points) < 4 or not np.isfinite(points).all():
        raise ValueError("Invalid OCR bounding box")
    return points.tolist()


def infer(image, engine):
    languages = tuple(x.strip() for x in settings.ocr_languages.split(",") if x.strip())
    model = reader(engine, languages)
    if engine == "easyocr":
        return [
            (str(text), float(score), polygon(box), engine)
            for box, text, score in model.readtext(image)
        ]
    lines = []
    for result in model.predict(image):
        boxes = result.get("rec_polys", result.get("rec_boxes", []))
        for text, score, box in zip(result["rec_texts"], result["rec_scores"], boxes):
            lines.append((str(text), float(score), polygon(box), engine))
    return lines


def recognize_image(image, engine, config):
    engines = (
        [engine]
        if engine != "auto"
        else [e for e, ok in available_engines().items() if ok]
    )
    if not engines:
        raise RuntimeError(
            "No OCR engine installed. Install requirements-ocr.txt and provision model weights."
        )
    errors = []
    for selected in engines:
        try:
            original = infer(np.asarray(image.convert("RGB")), selected)
            if not any(config.values()):
                return original
            processed = infer(preprocess(image, config), selected)

            # Compare variants; never merge their boxes or silently change coordinates.
            def quality(rows):
                return sum(score * len(text.strip()) for text, score, _, _ in rows)

            return processed if quality(processed) > quality(original) else original
        except Exception as exc:
            logger.exception("OCR engine %s failed", selected)
            errors.append(f"{selected}: {type(exc).__name__}: {str(exc)[:300]}")
    raise RuntimeError("; ".join(errors))


def recognize(page_bytes, engine="auto"):
    with Image.open(io.BytesIO(page_bytes)) as image:
        return [(t, c, b) for t, c, b, _ in recognize_image(image, engine, {})]
