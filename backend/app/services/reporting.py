import json
import pymupdf as fitz


def wrap_line(text, max_width=523):
    line = ""
    width = 0
    for char in text:
        char_width = fitz.get_text_length(char, fontname="japan", fontsize=10)
        if char == "\n" or width + char_width > max_width:
            yield line
            line = ""
            width = 0
        if char != "\n":
            line += char
            width += char_width
    yield line


def render_lines(lines, footer):
    with fitz.open() as pdf:
        page = None
        y = 0
        for line in lines:
            for wrapped in wrap_line(line):
                if page is None or y > 785:
                    page = pdf.new_page(width=595, height=842)
                    y = 42
                page.insert_text((36, y), wrapped, fontname="japan", fontsize=10)
                y += 15
        for number, report_page in enumerate(pdf, 1):
            report_page.insert_text(
                (36, 820),
                f"{footer} | Page {number} of {len(pdf)}",
                fontname="helv",
                fontsize=8,
            )
        return pdf.tobytes(garbage=4, deflate=True)


def project_pdf(project, summary):
    lines = [
        "ENGINEERING DRAWING INTELLIGENCE - PROJECT SUMMARY",
        f"Project: {project.name}",
        f"Description: {project.description or '-'}",
        f"Documents: {summary['documents']} | Pages: {summary['pages']}",
        f"Processing: {json.dumps(summary['processing'])}",
        f"Material annotations: {summary['materials']}",
        f"Classifications: {json.dumps(summary['classifications'])}",
        f"Categories: {json.dumps(summary['categories'], ensure_ascii=False)}",
        "Decision support only. Professional surveying and source verification are required.",
        "",
    ]
    for item in summary["items"]:
        c = item["classifications"]
        lines.append(
            f"#{item['id']} {item['filename']} [{item['status']}] "
            f"asbestos {c['ASBESTOS_CONTAINING']} / non-asbestos {c['NON_ASBESTOS']} "
            f"/ manual review {c['MANUAL_REVIEW']}"
        )
    if not summary["items"]:
        lines.append("No documents in this project.")
    return render_lines(lines, f"Project {project.id}")


def pdf_report(document, result):
    lines = [
        "ENGINEERING DRAWING INTELLIGENCE",
        f"Document: {document.filename}",
        f"Uploaded: {document.created_at.isoformat()}",
        f"Pages: {document.pages}",
        f"Analysis: {result['job']['id']} / {result['job']['engine']}",
        f"Preprocessing: {result['job']['preprocessing']}",
        f"Runtime configuration: {result['job'].get('runtime_config', {})}",
        "Decision support only. Professional surveying and source verification are required.",
        "Original AI classifications are retained alongside subsequent human review.",
        "",
    ]
    for finding in result["findings"]:
        if not finding["is_material"]:
            continue
        lines.extend(
            [
                f"Page {finding['page']} | Finding {finding['id']}",
                f"Source: {finding['source_text']}",
                f"Material: {finding['normalized_name']}",
                f"AI result: {finding['classification']}",
                f"OCR engine: {finding['engine']}",
                f"OCR: {finding['confidence']:.3f} | Match: {finding['match_score']:.3f} ({finding['method']})",
                f"Coordinates: {finding['bbox']}",
                f"Explanation: {finding['explanation']}",
                f"Reference snapshot: {json.dumps(finding['reference'], ensure_ascii=False)}",
                f"Review: {json.dumps(finding['review'], default=str, ensure_ascii=False)}",
                "",
            ]
        )
    if not any(f["is_material"] for f in result["findings"]):
        lines.append(
            "No material annotations identified. This does not establish absence of asbestos."
        )
    with fitz.open() as pdf:
        page = None
        y = 0
        for line in lines:
            for wrapped in wrap_line(line):
                if page is None or y > 785:
                    page = pdf.new_page(width=595, height=842)
                    y = 42
                # Built-in CJK font also supports English and Japanese OCR annotations.
                page.insert_text((36, y), wrapped, fontname="japan", fontsize=10)
                y += 15
        for number, report_page in enumerate(pdf, 1):
            report_page.insert_text(
                (36, 820),
                f"Analysis {result['job']['id']} | Page {number} of {len(pdf)}",
                fontname="helv",
                fontsize=8,
            )
        return pdf.tobytes(garbage=4, deflate=True)
