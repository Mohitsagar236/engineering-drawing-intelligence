import re
from rapidfuzz import fuzz
from sqlalchemy.orm import Session
from app.models.models import Material

SEED = [
    ("Asbestos cement board", "ACB|asbestos cement|cement board", "Board", "CONTAINS_ASBESTOS"),
    ("Vinyl floor tile", "vinyl tile|VCT|floor tile", "Flooring", "CONDITION_DEPENDENT"),
    ("Glass wool insulation", "glass wool|fiberglass insulation", "Insulation", "DOES_NOT_CONTAIN_ASBESTOS"),
]
def seed(db: Session):
    if db.query(Material).count(): return
    for name, aliases, category, status in SEED:
        db.add(Material(standard_name=name, aliases=aliases, category=category, asbestos_status=status))
    db.commit()

def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

def match(db: Session, text: str):
    candidate = normalize(text)
    best, score = None, 0
    for material in db.query(Material).all():
        for alias in [material.standard_name, *material.aliases.split("|")]:
            current = fuzz.token_set_ratio(candidate, normalize(alias))
            if current > score: best, score = material, current
    # Safety invariant: only explicit verified statuses can leave manual review.
    if not best or score < 86 or best.asbestos_status in ("UNKNOWN", "CONDITION_DEPENDENT"):
        return (text, "MANUAL_REVIEW", score / 100)
    classification = "ASBESTOS_CONTAINING" if best.asbestos_status == "CONTAINS_ASBESTOS" else "NON_ASBESTOS"
    return (best.standard_name, classification, score / 100)
