from app.services.materials import normalize, match
from app.db.session import Base, engine, SessionLocal
from app.models.models import Material

def test_normalize():
    assert normalize(" VCT / Floor-Tile ") == "vct floortile"

def test_unknown_is_manual_review():
    Base.metadata.create_all(engine)
    db = SessionLocal()
    db.query(Material).delete()
    db.add(Material(standard_name="Known", aliases="known", asbestos_status="DOES_NOT_CONTAIN_ASBESTOS", verification_status="UNVERIFIED"))
    db.commit()
    assert match(db, "Known")[1] == "MANUAL_REVIEW"
    db.close()
