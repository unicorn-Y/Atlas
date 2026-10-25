"""Deterministic local media extraction with bounded, auditable context blocks."""

from __future__ import annotations

import hashlib
import io
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

MAX_EXTRACTED_CHARS = 100_000
_OFFICE_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _audit(name: str, mime: str, payload: bytes, extractor: str, status: str, chars: int = 0) -> dict[str, Any]:
    return {
        "kind": "media_understanding", "name": name[:160], "mime": mime[:120],
        "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload),
        "extractor": extractor, "status": status, "characters": chars,
    }


def _pdf_text(payload: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(payload), strict=False)
    pages = []
    for page in reader.pages[:200]:
        text = (page.extract_text() or "").strip()
        if text:
            pages.append(text)
        if sum(map(len, pages)) >= MAX_EXTRACTED_CHARS:
            break
    return "\n\n".join(pages)[:MAX_EXTRACTED_CHARS]


def _docx_text(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs = []
    for paragraph in root.iter(f"{_OFFICE_NS}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{_OFFICE_NS}t")).strip()
        if text:
            paragraphs.append(text)
        if sum(map(len, paragraphs)) >= MAX_EXTRACTED_CHARS:
            break
    return "\n".join(paragraphs)[:MAX_EXTRACTED_CHARS]


def _xlsx_text(payload: bytes) -> str:
    from openpyxl import load_workbook

    workbook = load_workbook(io.BytesIO(payload), read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in workbook.worksheets[:40]:
            lines.append(f"## {sheet.title}")
            for row in sheet.iter_rows(values_only=True):
                values = [str(value) if value is not None else "" for value in row]
                if any(values):
                    lines.append("\t".join(values))
                if sum(map(len, lines)) >= MAX_EXTRACTED_CHARS:
                    break
            if sum(map(len, lines)) >= MAX_EXTRACTED_CHARS:
                break
    finally:
        workbook.close()
    return "\n".join(lines)[:MAX_EXTRACTED_CHARS]


def extract_document(name: str, mime: str, payload: bytes) -> tuple[str, dict[str, Any]]:
    """Extract supported textual formats; unknown binary files stay as attachments."""
    suffix = Path(name).suffix.lower()
    if mime.startswith("text/") or mime in {"application/json", "text/markdown"} or suffix in {
        ".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".tsx", ".jsx",
        ".html", ".css", ".yaml", ".yml", ".toml", ".xml", ".sql", ".sh", ".ps1",
        ".go", ".rs", ".java", ".c", ".h", ".cpp", ".hpp", ".rb", ".php", ".swift", ".kt",
    }:
        try:
            text = payload.decode("utf-8")[:MAX_EXTRACTED_CHARS]
        except UnicodeDecodeError:
            return "", _audit(name, mime, payload, "utf-8", "failed")
        return text, _audit(name, mime, payload, "utf-8", "complete", len(text))
    extractor = {".pdf": "pypdf", ".docx": "docx-xml", ".xlsx": "openpyxl"}.get(suffix)
    if not extractor:
        return "", _audit(name, mime, payload, "none", "not_supported")
    try:
        text = {".pdf": _pdf_text, ".docx": _docx_text, ".xlsx": _xlsx_text}[suffix](payload)
    except Exception as exc:
        return "", _audit(name, mime, payload, extractor, f"failed:{type(exc).__name__}")
    status = "complete" if text.strip() else "no_text"
    return text, _audit(name, mime, payload, extractor, status, len(text))


def ocr_image_data_url(data_url: str, index: int) -> tuple[str, dict[str, Any]]:
    """Use local Tesseract when installed; the original image remains vision context."""
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})", data_url)
    if not match:
        return "", {"kind": "media_understanding", "name": f"image-{index + 1}", "extractor": "tesseract", "status": "invalid_image"}
    import base64

    payload = base64.b64decode(match.group(2), validate=True)
    if not shutil.which("tesseract"):
        return "", _audit(f"image-{index + 1}", match.group(1), payload, "tesseract", "unavailable")
    try:
        from PIL import Image
        import pytesseract

        image = Image.open(io.BytesIO(payload))
        text = pytesseract.image_to_string(image, timeout=15).strip()[:MAX_EXTRACTED_CHARS]
    except Exception as exc:
        return "", _audit(f"image-{index + 1}", match.group(1), payload, "tesseract", f"failed:{type(exc).__name__}")
    return text, _audit(f"image-{index + 1}", match.group(1), payload, "tesseract", "complete" if text else "no_text", len(text))


def media_context_block(audit: dict[str, Any], text: str) -> str:
    """Build transcript context with a reproducible source digest and extraction method."""
    if not text.strip():
        return ""
    return (
        f"--- Media text extraction: {audit.get('name')} | method={audit.get('extractor')} "
        f"| sha256={audit.get('sha256', 'unavailable')} | chars={len(text)} ---\n{text}"
    )
