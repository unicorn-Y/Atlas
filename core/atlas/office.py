"""Create, read, and safely preview Office files without executing embedded content."""

from __future__ import annotations

import base64
import html
import io
import mimetypes
from pathlib import Path
from typing import Any

MAX_PREVIEW_BYTES = 10 * 1024 * 1024


def _target(root: str, value: str) -> Path:
    base = Path(root).expanduser().resolve()
    candidate = Path(value).expanduser()
    candidate = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    if candidate == base or base not in candidate.parents:
        raise ValueError("Office files must stay inside the workspace")
    return candidate


def _image(root: str, value: str) -> Path:
    path = _target(root, value)
    if not path.is_file():
        raise ValueError(f"Image file not found: {value}")
    return path


def create_document(root: str, spec: dict[str, Any]) -> dict[str, Any]:
    from docx import Document
    from docx.shared import Inches

    target = _target(root, str(spec["path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    document = Document()
    document.core_properties.title = str(spec.get("title") or "")
    for block in spec.get("blocks", []):
        kind = block.get("type")
        if kind == "heading":
            document.add_heading(str(block.get("text", "")), level=int(block.get("level", 1)))
        elif kind == "paragraph":
            document.add_paragraph(str(block.get("text", "")))
        elif kind == "bullets":
            for item in block.get("items", []):
                document.add_paragraph(str(item), style="List Bullet")
        elif kind == "table":
            rows = block.get("rows", [])
            if rows:
                table = document.add_table(rows=0, cols=max(len(row) for row in rows))
                table.style = "Table Grid"
                for row in rows:
                    cells = table.add_row().cells
                    for index, value in enumerate(row):
                        cells[index].text = str(value)
        elif kind == "image":
            image_path = _image(root, str(block.get("path", "")))
            document.add_picture(str(image_path), width=Inches(float(block.get("width", 5))))
        else:
            raise ValueError(f"Unsupported document block: {kind}")
    document.save(target)
    return {"path": str(target), "kind": "document", "bytes": target.stat().st_size}


def create_spreadsheet(root: str, spec: dict[str, Any]) -> dict[str, Any]:
    from openpyxl import Workbook
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    target = _target(root, str(spec["path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet_spec in spec.get("sheets", []):
        sheet = workbook.create_sheet(str(sheet_spec.get("name") or "Sheet"))
        header = bool(sheet_spec.get("header", False))
        for row_number, row in enumerate(sheet_spec.get("rows", []), 1):
            for column_number, value in enumerate(row, 1):
                cell = sheet.cell(row=row_number, column=column_number, value=value)
                if header and row_number == 1:
                    cell.font = Font(bold=True)
        if header:
            sheet.freeze_panes = "A2"
        for index, width in enumerate(sheet_spec.get("column_widths", []), 1):
            sheet.column_dimensions[get_column_letter(index)].width = float(width)
    workbook.save(target)
    return {"path": str(target), "kind": "spreadsheet", "bytes": target.stat().st_size}


def create_presentation(root: str, spec: dict[str, Any]) -> dict[str, Any]:
    from pptx import Presentation
    from pptx.util import Inches

    target = _target(root, str(spec["path"]))
    target.parent.mkdir(parents=True, exist_ok=True)
    presentation = Presentation()
    for slide_spec in spec.get("slides", []):
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = str(slide_spec.get("title", ""))
        body = slide.placeholders[1].text_frame
        body.clear()
        for index, bullet in enumerate(slide_spec.get("bullets", [])):
            paragraph = body.paragraphs[0] if index == 0 else body.add_paragraph()
            paragraph.text = str(bullet)
            paragraph.level = 0
        if slide_spec.get("image"):
            image = _image(root, str(slide_spec["image"]))
            slide.shapes.add_picture(
                str(image), Inches(7), Inches(1.5), width=Inches(5.5),
            )
        if slide_spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = str(slide_spec["notes"])
    presentation.save(target)
    return {"path": str(target), "kind": "presentation", "bytes": target.stat().st_size}


def read_office(path: str) -> dict[str, Any]:
    source = Path(path)
    suffix = source.suffix.casefold()
    if suffix == ".docx":
        from docx import Document

        document = Document(source)
        return {
            "kind": "document",
            "paragraphs": [paragraph.text for paragraph in document.paragraphs if paragraph.text],
            "tables": [[[cell.text for cell in row.cells] for row in table.rows]
                       for table in document.tables],
        }
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(source, read_only=True, data_only=False)
        try:
            return {"kind": "spreadsheet", "sheets": [{
                "name": sheet.title,
                "rows": [[str(value) if value is not None else None for value in row]
                         for row in sheet.iter_rows(min_row=1, max_row=200, values_only=True)],
                "truncated": sheet.max_row > 200,
            } for sheet in workbook.worksheets]}
        finally:
            workbook.close()
    if suffix == ".pptx":
        from pptx import Presentation

        presentation = Presentation(source)
        slides = []
        for slide in presentation.slides:
            title = slide.shapes.title.text if slide.shapes.title else ""
            bullets = [
                paragraph.text for shape in slide.shapes if getattr(shape, "has_text_frame", False)
                and shape != slide.shapes.title
                for paragraph in shape.text_frame.paragraphs if paragraph.text
            ]
            slides.append({"title": title, "bullets": bullets})
        return {"kind": "presentation", "slides": slides}
    raise ValueError("Only .docx, .xlsx, and .pptx files are supported")


def _data_url(blob: bytes, content_type: str) -> str:
    return f"data:{content_type};base64,{base64.b64encode(blob).decode('ascii')}"


def _document_images(document: Any) -> list[str]:
    images = []
    for relation in document.part.rels.values():
        if relation.reltype.endswith("/image"):
            content_type = relation.target_part.content_type
            images.append(
                f'<img alt="" src="{_data_url(relation.target_part.blob, content_type)}">'
            )
    return images


def render_office(raw: bytes, suffix: str) -> str:
    if len(raw) > MAX_PREVIEW_BYTES:
        raise ValueError("Office preview is limited to 10 MB")
    suffix = suffix.casefold()
    sections: list[str] = []
    if suffix == ".docx":
        from docx import Document

        document = Document(io.BytesIO(raw))
        for paragraph in document.paragraphs:
            text = html.escape(paragraph.text)
            if not text:
                continue
            style = paragraph.style.name.casefold()
            if style.startswith("heading"):
                try:
                    level = min(6, max(1, int(style.removeprefix("heading "))))
                except ValueError:
                    level = 2
                sections.append(f"<h{level}>{text}</h{level}>")
            else:
                sections.append(f"<p>{text}</p>")
        for table in document.tables:
            sections.append("<table><tbody>")
            for row in table.rows:
                sections.append("<tr>" + "".join(
                    f"<td>{html.escape(cell.text)}</td>" for cell in row.cells
                ) + "</tr>")
            sections.append("</tbody></table>")
        sections.extend(_document_images(document))
    elif suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=False)
        try:
            for sheet in workbook.worksheets:
                sections.append(f"<section><h2>{html.escape(sheet.title)}</h2><table><tbody>")
                for row_number, row in enumerate(sheet.iter_rows(values_only=True), 1):
                    if row_number > 500:
                        sections.append("<tr><td>Preview limited to 500 rows</td></tr>")
                        break
                    sections.append("<tr>" + "".join(
                        f"<td>{html.escape(str(value)) if value is not None else ''}</td>"
                        for value in row
                    ) + "</tr>")
                sections.append("</tbody></table></section>")
        finally:
            workbook.close()
    elif suffix == ".pptx":
        from pptx import Presentation

        presentation = Presentation(io.BytesIO(raw))
        for index, slide in enumerate(presentation.slides, 1):
            title = slide.shapes.title.text if slide.shapes.title else f"Slide {index}"
            sections.append(f"<section class=\"slide\"><h2>{html.escape(title)}</h2>")
            for shape in slide.shapes:
                if shape == slide.shapes.title:
                    continue
                if getattr(shape, "has_text_frame", False):
                    for paragraph in shape.text_frame.paragraphs:
                        if paragraph.text:
                            sections.append(f"<p>{html.escape(paragraph.text)}</p>")
                if getattr(shape, "shape_type", None) == 13:
                    image = shape.image
                    mime = mimetypes.guess_type("image." + image.ext)[0] or "image/png"
                    sections.append(f'<img alt="" src="{_data_url(image.blob, mime)}">')
            sections.append("</section>")
    else:
        raise ValueError("Only .docx, .xlsx, and .pptx files can be previewed")
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><style>"
        "body{font:15px system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#20242a}"
        "table{border-collapse:collapse;margin:1rem 0;width:100%}td{border:1px solid #bbb;padding:.4rem}"
        "img{max-width:100%;height:auto}.slide{border-bottom:1px solid #bbb;padding:1rem 0}"
        "</style></head><body>" + "".join(sections) + "</body></html>"
    )
