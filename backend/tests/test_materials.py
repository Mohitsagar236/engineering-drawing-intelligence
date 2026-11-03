import pytest
from app.models.models import Material
from app.services.materials import analyze, normalize, seed


def reference(db, **kwargs):
    material = Material(
        standard_name="Product X-100",
        aliases="PX100",
        asbestos_status="DOES_NOT_CONTAIN_ASBESTOS",
        verification_status="VERIFIED",
        source="Laboratory reference certificate ABC123",
        **kwargs,
    )
    db.add(material)
    db.commit()
    return material


def test_normalization_preserves_japanese_and_separates_punctuation():
    assert normalize("  VCT / Floor-Tile  ") == "vct floor tile"
    assert normalize("石綿 含有") == "石綿 含有"


def test_seed_is_never_authoritative(db):
    seed(db)
    assert analyze(db, "Glass wool insulation", 1)["classification"] == "MANUAL_REVIEW"
    assert all(m.verification_status == "DEMONSTRATION" for m in db.query(Material))


def test_exact_verified_reference_can_classify(db):
    reference(db)
    assert analyze(db, "PX100", 0.99)["classification"] == "NON_ASBESTOS"


@pytest.mark.parametrize(
    "text,confidence",
    [("PX100", 0.5), ("Product X-10O", 0.99), ("arbitrary annotation", 1)],
)
def test_uncertain_results_always_require_review(db, text, confidence):
    reference(db)
    assert analyze(db, text, confidence)["classification"] == "MANUAL_REVIEW"


def test_conflicting_aliases_require_review(db):
    reference(db)
    db.add(
        Material(
            standard_name="Different product",
            aliases="PX100",
            source="Conflicting laboratory reference",
            verification_status="VERIFIED",
            asbestos_status="CONTAINS_ASBESTOS",
        )
    )
    db.commit()
    assert analyze(db, "PX100", 1)["classification"] == "MANUAL_REVIEW"


def test_conditions_require_review(db):
    reference(db, conditions="Only products manufactured after 2010")
    assert analyze(db, "PX100", 1)["classification"] == "MANUAL_REVIEW"


def test_unverified_record_requires_review(db):
    material = reference(db)
    material.verification_status = "UNVERIFIED"
    db.commit()
    assert analyze(db, "PX100", 1)["classification"] == "MANUAL_REVIEW"
