"""Evaluate deterministic matching rules in an isolated synthetic reference catalog."""

import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.db.session import Base
from app.models.models import Material
from app.services.materials import analyze

labels = ["ASBESTOS_CONTAINING", "NON_ASBESTOS", "MANUAL_REVIEW"]
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(engine)
cases = [
    ("TEST-POSITIVE", 0.99, "ASBESTOS_CONTAINING"),
    ("TEST-NEGATIVE", 0.99, "NON_ASBESTOS"),
    ("TEST-POSIT1VE", 0.99, "MANUAL_REVIEW"),
    ("TEST-NEGATIVE", 0.2, "MANUAL_REVIEW"),
    ("UNKNOWN PRODUCT", 0.99, "MANUAL_REVIEW"),
    ("TEST-CONDITIONAL", 0.99, "MANUAL_REVIEW"),
    ("TEST-UNVERIFIED", 0.99, "MANUAL_REVIEW"),
]
with Session(engine) as db:
    for name, status, verification, conditions in [
        ("TEST-POSITIVE", "CONTAINS_ASBESTOS", "VERIFIED", ""),
        ("TEST-NEGATIVE", "DOES_NOT_CONTAIN_ASBESTOS", "VERIFIED", ""),
        (
            "TEST-CONDITIONAL",
            "DOES_NOT_CONTAIN_ASBESTOS",
            "VERIFIED",
            "Only under verified installation conditions",
        ),
        ("TEST-UNVERIFIED", "DOES_NOT_CONTAIN_ASBESTOS", "UNVERIFIED", ""),
    ]:
        db.add(
            Material(
                standard_name=name,
                asbestos_status=status,
                verification_status=verification,
                conditions=conditions,
                source="SYNTHETIC TEST EVIDENCE — no real product claim",
            )
        )
    db.commit()
    matrix = {actual: {predicted: 0 for predicted in labels} for actual in labels}
    for text, confidence, expected in cases:
        predicted = analyze(db, text, confidence)["classification"]
        matrix[expected][predicted] += 1
    metrics = {}
    for label in labels:
        true = matrix[label][label]
        precision = true / max(1, sum(matrix[other][label] for other in labels))
        recall = true / max(1, sum(matrix[label].values()))
        metrics[label] = {
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / max(1e-10, precision + recall),
        }
    print(
        json.dumps(
            {
                "dataset": "synthetic-safety-rules-v1",
                "cases": len(cases),
                "metrics": metrics,
                "confusion_matrix_actual_rows_predicted_columns": matrix,
                "limitation": "Deterministic rule evaluation on synthetic references; not field material-extraction accuracy.",
            },
            indent=2,
        )
    )
