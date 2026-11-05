"""Drawing-specific extraction from recognized OCR annotations.

Works purely on stored text and polygons, so it applies to any completed
analysis (including historical runs) without re-running OCR. Results are
heuristic and carry the source annotation so a person can verify each value.
"""

import re
from statistics import median

TITLE_FIELDS = {
    "title": ("DRAWING TITLE", "TITLE", "DWG TITLE", "NAME"),
    "drawing_number": (
        "DRAWING NUMBER",
        "DRAWING NO",
        "DWG NUMBER",
        "DWG NO",
        "DWG",
        "PART NO",
        "PART NUMBER",
        "DOC NO",
    ),
    "revision": ("REVISION", "REV"),
    "scale": ("SCALE",),
    "date": ("DATE",),
    "drawn_by": ("DRAWN BY", "DRAWN", "DESIGNED BY", "DESIGNER"),
    "checked_by": ("CHECKED BY", "CHECKED", "CHK"),
    "approved_by": ("APPROVED BY", "APPROVED", "APPR"),
    "material": ("MATERIAL", "MATL"),
    "sheet": ("SHEET", "SHEET NO"),
    "project": ("PROJECT",),
    "company": ("COMPANY", "CLIENT", "CUSTOMER"),
}
BOM_HEADERS = {
    "item": ("ITEM", "ITEM NO", "NO", "NO.", "POS", "BALLOON", "#"),
    "part_number": ("PART NO", "PART NUMBER", "PART", "P/N", "CODE"),
    "description": ("DESCRIPTION", "DESC", "NAME", "TITLE"),
    "material": ("MATERIAL", "MATL", "MAT"),
    "quantity": ("QTY", "QUANTITY", "QTY.", "NO OFF"),
    "remarks": ("REMARKS", "NOTES", "NOTE"),
}
NUMBER = r"\d+(?:[.,]\d+)?"
DIMENSION = re.compile(
    rf"^(?P<prefix>[ØøΦφ⌀]|R|M|DIA\.?|SR)?\s*(?P<value>{NUMBER})"
    rf"(?:\s*(?P<tol>(?:±|\+/-)\s*{NUMBER}|[+-]\s*{NUMBER}\s*/\s*[+-]\s*{NUMBER}))?"
    r"\s*(?P<unit>mm|cm|m|in|inch|\"|°|deg)?$",
    re.IGNORECASE,
)


def clean(text):
    return re.sub(r"\s+", " ", text).strip()


def label_key(text):
    return re.sub(r"[^A-Z0-9/# ]+", "", text.upper()).strip()


def geometry(finding):
    points = finding["bbox"]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def match_label(text, table):
    """Return (field, remainder) when text begins with a known label."""
    upper = text.upper()
    best = None
    for field, labels in table.items():
        for label in labels:
            pattern = rf"^{re.escape(label)}(?![A-Z0-9])\s*[:.\-]?\s*(.*)$"
            found = re.match(pattern, upper)
            if found and (best is None or len(label) > best[2]):
                best = (field, text[len(text) - len(found.group(1)) :], len(label))
    return (best[0], clean(best[1])) if best else None


def source(finding):
    return {
        "finding_id": finding["id"],
        "page": finding["page"],
        "confidence": finding["confidence"],
        "bbox": finding["bbox"],
    }


def title_block(findings, pages):
    sizes = {p["number"]: p for p in pages}
    fields = {}
    for finding in findings:
        labelled = match_label(clean(finding["source_text"]), TITLE_FIELDS)
        if not labelled:
            continue
        field, inline = labelled
        left, top, right, bottom = geometry(finding)
        height = max(1, bottom - top)
        value, origin = inline, finding
        if not value:
            candidates = []
            for other in findings:
                if other is finding or other["page"] != finding["page"]:
                    continue
                if match_label(clean(other["source_text"]), TITLE_FIELDS):
                    continue
                ol, ot, orr, ob = geometry(other)
                same_line = abs((ot + ob) / 2 - (top + bottom) / 2) < height
                below = 0 < ot - bottom < height * 3 and ol < right and orr > left
                if (same_line and ol >= right - height) or below:
                    distance = abs(ol - right) + abs(ot - top) * 2
                    candidates.append((distance, other))
            if not candidates:
                continue
            origin = min(candidates, key=lambda c: c[0])[1]
            value = clean(origin["source_text"])
        # Title blocks sit at the bottom of the sheet; prefer that region.
        page = sizes.get(finding["page"])
        in_block = bool(page and top > page["height"] * 0.6)
        rank = (in_block, finding["confidence"])
        if field not in fields or rank > fields[field]["_rank"]:
            fields[field] = {
                "field": field,
                "value": value,
                "source": source(origin),
                "_rank": rank,
            }
    return [
        {k: v for k, v in entry.items() if k != "_rank"}
        for entry in sorted(
            fields.values(), key=lambda e: list(TITLE_FIELDS).index(e["field"])
        )
    ]


def dimensions(findings):
    found = []
    for finding in findings:
        text = clean(finding["source_text"])
        parsed = DIMENSION.match(text)
        if not parsed:
            continue
        prefix = (parsed["prefix"] or "").upper()
        unit = (parsed["unit"] or "").lower()
        if not (prefix or unit or parsed["tol"] or "." in text or "," in text):
            if len(parsed["value"]) > 5:
                continue
        if unit in ("°", "deg"):
            kind = "angle"
        elif prefix in ("Ø", "Ф", "Φ", "φ", "⌀", "DIA", "DIA."):
            kind = "diameter"
        elif prefix in ("R", "SR"):
            kind = "radius"
        elif prefix == "M":
            kind = "thread"
        else:
            kind = "linear"
        found.append(
            {
                "text": text,
                "kind": kind,
                "value": float(parsed["value"].replace(",", ".")),
                "unit": "in" if unit in ("inch", '"') else unit,
                "tolerance": clean(parsed["tol"] or ""),
                "source": source(finding),
            }
        )
    return found


def bom_tables(findings):
    tables = []
    for page in sorted({f["page"] for f in findings}):
        items = [f for f in findings if f["page"] == page]
        boxes = {f["id"]: geometry(f) for f in items}
        headers = []
        for finding in items:
            labelled = match_label(clean(finding["source_text"]), BOM_HEADERS)
            if labelled and not labelled[1]:
                headers.append((labelled[0], finding))
        if len({h[0] for h in headers}) < 2:
            continue
        # Header cells share a row; keep the densest row.
        rows = {}
        for field, finding in headers:
            top, bottom = boxes[finding["id"]][1], boxes[finding["id"]][3]
            rows.setdefault(
                round(((top + bottom) / 2) / max(1, bottom - top)), []
            ).append((field, finding))
        header_row = max(rows.values(), key=len)
        if len({h[0] for h in header_row}) < 2:
            continue
        columns = sorted(
            {field: finding for field, finding in header_row}.items(),
            key=lambda c: boxes[c[1]["id"]][0],
        )
        header_ids = {f["id"] for _, f in header_row}
        bottoms = [boxes[f["id"]][3] for _, f in header_row]
        heights = [boxes[f["id"]][3] - boxes[f["id"]][1] for _, f in header_row]
        row_height = max(1, median(heights))
        table_left = min(boxes[f["id"]][0] for _, f in header_row) - row_height
        table_right = max(boxes[f["id"]][2] for _, f in header_row) + row_height * 4
        start = max(bottoms)
        body = [
            f
            for f in items
            if f["id"] not in header_ids
            and boxes[f["id"]][1] >= start - row_height * 0.3
            and boxes[f["id"]][0] >= table_left
            and boxes[f["id"]][0] <= table_right
        ]
        # Tables may be read top-down or bottom-up; take the side with content.
        body.sort(key=lambda f: boxes[f["id"]][1])
        lines, last = [], None
        for finding in body:
            top = boxes[finding["id"]][1]
            if last is not None and top - last > row_height * 4:
                break
            if lines and abs(top - lines[-1]["y"]) <= row_height * 0.7:
                lines[-1]["cells"].append(finding)
            else:
                lines.append({"y": top, "cells": [finding]})
            last = boxes[finding["id"]][3]
        lefts = [boxes[f["id"]][0] for _, f in columns]
        output = []
        for line in lines:
            row = {field: "" for field, _ in columns}
            sources = []
            for cell in sorted(line["cells"], key=lambda f: boxes[f["id"]][0]):
                x = boxes[cell["id"]][0]
                index = min(range(len(lefts)), key=lambda i: abs(lefts[i] - x))
                field = columns[index][0]
                row[field] = clean(f"{row[field]} {cell['source_text']}")
                sources.append(source(cell))
            output.append({"cells": row, "sources": sources})
        if output:
            tables.append(
                {
                    "page": page,
                    "columns": [field for field, _ in columns],
                    "rows": output,
                }
            )
    return tables


def extract(findings, pages):
    return {
        "title_block": title_block(findings, pages),
        "dimensions": dimensions(findings),
        "bom": bom_tables(findings),
    }
