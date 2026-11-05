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


@pytest.mark.parametrize(
    "text",
    [
        "Academic Section",
        "A+",
        "A-",
        "B",
        "B-",
        "C",
        "LOO",
        "1.00",
        "2.00",
        "Physics Lab",
        "Fluid Mechanics Lab",
        "ES Project",
        "AIITIO",
        "Course Name",
        "Introduction to Materials Science and Engineering",
    ],
)
def test_unrelated_academic_text_does_not_become_material(db, text):
    from app.services.materials import is_material

    seed(db)
    result = analyze(db, text, 0.99)
    assert result["material_id"] is None
    assert result["name"] == text
    assert result["method"] == "none"
    assert result["alternatives"] == []
    assert not is_material(text, result)


def test_fuzzy_spelling_is_only_a_suggestion_and_preserves_source(db):
    from app.services.materials import is_material

    seed(db)
    text = "Vinyl floor ti1e"
    result = analyze(db, text, 0.99)
    assert result["name"] == text
    assert result["method"] == "fuzzy"
    assert result["snapshot"]["standard_name"] == "Vinyl floor tile"
    assert result["classification"] == "MANUAL_REVIEW"
    assert is_material(text, result)


def test_very_low_confidence_text_does_not_gain_a_fuzzy_identity(db):
    seed(db)
    result = analyze(db, "G1ass woo1 insu1ation", 0.1)
    assert result["material_id"] is None
    assert result["name"] == "G1ass woo1 insu1ation"


def test_real_abbreviations_still_match_exactly(db):
    seed(db)
    for text in ("ACB", "VCT"):
        result = analyze(db, text, 0.99)
        assert result["method"] == "exact"
        assert result["material_id"] is not None


def test_conflicting_aliases_do_not_select_an_arbitrary_product(db):
    reference(db)
    db.add(Material(standard_name="Another product", aliases="PX100"))
    db.commit()
    result = analyze(db, "PX100", 0.99)
    assert result["method"] == "ambiguous"
    assert result["material_id"] is None
    assert result["snapshot"] == {}
    assert len(result["alternatives"]) == 2
