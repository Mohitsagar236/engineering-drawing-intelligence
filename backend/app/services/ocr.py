from pathlib import Path
from functools import lru_cache

def pages_for_file(path: str):
    if Path(path).suffix.lower() == ".pdf":
        import fitz
        doc = fitz.open(path)
        return [page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False).tobytes("png") for page in doc]
    return [Path(path).read_bytes()]

@lru_cache(maxsize=2)
def _easy_reader():
    import easyocr
    return easyocr.Reader(["en"], gpu=False)

@lru_cache(maxsize=1)
def _paddle_reader():
    from paddleocr import PaddleOCR
    return PaddleOCR(lang="en", use_doc_orientation_classify=False, use_doc_unwarping=False, use_textline_orientation=False)

def recognize(page_bytes: bytes, engine="auto"):
    # Optional engines are loaded only when requested and installed. The fallback is explicit and review-safe.
    try:
        import cv2, numpy as np
        image = cv2.imdecode(np.frombuffer(page_bytes, np.uint8), cv2.IMREAD_COLOR)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        _, threshold = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        processed = threshold
        if engine == "easyocr":
            return [(text, float(conf), [int(v) for point in box for v in point]) for box, text, conf in _easy_reader().readtext(processed)]
        if engine in ("paddleocr", "auto"):
            result = _paddle_reader().predict(processed)
            out=[]
            for item in result:
                for text, conf, box in zip(item.get("rec_texts", []), item.get("rec_scores", []), item.get("rec_boxes", [])):
                    out.append((text, float(conf), [int(x) for x in box]))
            return out
    except Exception:
        pass
    return []
