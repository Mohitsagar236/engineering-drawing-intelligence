import re
import math
import unicodedata
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.models import Material
from app.core.config import settings


def normalize(text):
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text)).strip()


def seed(db: Session):
    if db.query(Material).count():
        return
    for name, aliases, category in [
        ("Asbestos cement board", "ACB|asbestos cement", "Board"),
        ("Vinyl floor tile", "vinyl tile|VCT|floor tile", "Flooring"),
        ("Glass wool insulation", "glass wool|fiberglass insulation", "Insulation"),
    ]:
        db.add(
            Material(
                standard_name=name,
                aliases=aliases,
                category=category,
                asbestos_status="UNKNOWN",
                verification_status="DEMONSTRATION",
                source="DEMONSTRATION ONLY; replace with documented product-specific evidence",
            )
        )
    db.commit()


def analyze(db, text, ocr_confidence):
    value = normalize(text)
    ranked, exact = [], []
    for record in db.query(Material).all():
        names = [
            normalize(n)
            for n in [record.standard_name, *record.aliases.split("|")]
            if normalize(n)
        ]
        if not names:
            continue
        score = max(fuzz.WRatio(value, name) for name in names) / 100
        ranked.append((record, score))
        if value in names:
            exact.append(record)
    ranked.sort(key=lambda item: item[1], reverse=True)
    best = (
        exact[0]
        if len(exact) == 1
        else (ranked[0][0] if ranked and ranked[0][1] >= 0.65 else None)
    )
    result = dict(
        name=best.standard_name if best else text,
        classification="MANUAL_REVIEW",
        material_id=best.id if best else None,
        score=(1 if exact else ranked[0][1] if best else 0),
        method="exact" if exact else "fuzzy" if best else "none",
        explanation="No exact, unambiguous verified product reference matches this annotation.",
        snapshot={},
        alternatives=[
            dict(id=r.id, name=r.standard_name, score=s) for r, s in ranked[:3]
        ],
    )
    if best:
        result["snapshot"] = {
            k: getattr(best, k)
            for k in (
                "id",
                "standard_name",
                "asbestos_status",
                "verification_status",
                "conditions",
                "source",
                "category",
                "manufacturer",
                "description",
            )
        }
    if not value or len(exact) != 1:
        return result
    if (
        not math.isfinite(ocr_confidence)
        or not settings.ocr_min_confidence <= ocr_confidence <= 1
    ):
        result["explanation"] = "OCR confidence is below the decision threshold."
    elif best.verification_status != "VERIFIED":
        result["explanation"] = "Reference is unverified or demonstration data."
    elif not best.source.strip() or best.source.startswith(
        ("Local reference", "DEMONSTRATION")
    ):
        result["explanation"] = "Reference has no verified source."
    elif best.conditions.strip():
        result["explanation"] = (
            "Applicable product or installation conditions require human verification."
        )
    elif best.asbestos_status not in ("CONTAINS_ASBESTOS", "DOES_NOT_CONTAIN_ASBESTOS"):
        result["explanation"] = "Reference status is unknown or condition-dependent."
    else:
        result["classification"] = (
            "ASBESTOS_CONTAINING"
            if best.asbestos_status == "CONTAINS_ASBESTOS"
            else "NON_ASBESTOS"
        )
        result["explanation"] = (
            "Exact unique reference with verified source and sufficient OCR confidence."
        )
    return result


def match(db, text, ocr_confidence=0):
    result = analyze(db, text, ocr_confidence)
    return result["name"], result["classification"], result["score"]


def is_material(text, match_result):
    return bool(
        match_result["material_id"]
        or re.search(
            r"\b(asbestos|cement|board|tile|insulation|wool|plaster|gypsum|roof|pipe|cladding|floor|ceiling|concrete|steel|timber|vinyl|gasket|sealant|coating)\b",
            text,
            re.I,
        )
    )
