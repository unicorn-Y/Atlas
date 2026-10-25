"""Deterministic local media extraction with bounded, auditable context blocks."""

from __future__ import annotations

import hashlib
import io
import re
import threading
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from atlas.config import DATA_ROOT

MAX_EXTRACTED_CHARS = 100_000
_OFFICE_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_OCR_ROOT = DATA_ROOT / "data" / "models" / "ocr"
_OCR_MODELS = (
    ("PP-OCRv6_det_small.onnx",
     "https://huggingface.co/breezedeus/cnstd-ppocr-multi_PP-OCRv6_det_small/resolve/main/PP-OCRv6_det_small.onnx",
     10 * 1024 * 1024, "090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f"),
    ("PP-OCRv6_rec_small.onnx",
     "https://huggingface.co/breezedeus/cnocr-ppocr-multi_PP-OCRv6_small/resolve/main/PP-OCRv6_rec_small.onnx",
     24 * 1024 * 1024, "6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884"),
)
_OCR_MODEL_FILES = tuple(model[0] for model in _OCR_MODELS)
_OCR_LOCK = threading.Lock()
_OCR_PROGRESS: dict[str, Any] = {"state": "not_started", "progress": 0.0, "detail": ""}
_OCR_ENGINE: Any = None


def ocr_runtime_status() -> dict[str, Any]:
    """Return download/setup progress without exposing any user content."""
    present = []
    for name in _OCR_MODEL_FILES:
        final_path = _OCR_ROOT / name
        partial_path = final_path.with_suffix(final_path.suffix + ".part")
        present.append(final_path.stat().st_size if final_path.is_file() else
                       partial_path.stat().st_size if partial_path.is_file() else 0)
    downloaded = sum(present)
    # The default multilingual PP-OCRv6 pair is about 31 MiB. Keep progress useful
    # even on ModelScope responses which omit Content-Length.
    progress = min(0.98, downloaded / (32 * 1024 * 1024))
    ready = all((_OCR_ROOT / name).is_file() and (_OCR_ROOT / name).stat().st_size > 1024 * 1024
                for name in _OCR_MODEL_FILES)
    state = "ready" if ready else _OCR_PROGRESS.get("state", "not_started")
    return {**_OCR_PROGRESS, "state": state, "progress": 1.0 if ready else progress,
            "detail": "本地中英文 RapidOCR 模型已就绪" if ready else _OCR_PROGRESS.get("detail", ""),
            "ready": ready, "downloaded_bytes": downloaded}


def _ensure_rapidocr() -> Any:
    """Load RapidOCR with model assets stored under Atlas DATA_ROOT."""
    global _OCR_ENGINE
    with _OCR_LOCK:
        if _OCR_ENGINE is None:
            _OCR_ROOT.mkdir(parents=True, exist_ok=True)
            _OCR_PROGRESS.update(state="downloading", progress=0.0,
                                 detail="正在准备本地 RapidOCR 模型（简体中文与英文）")
            try:
                from rapidocr import RapidOCR
                from rapidocr.utils.typings import ModelType, OCRVersion
                total_size = 32 * 1024 * 1024
                for model_name, url, limit, expected_sha256 in _OCR_MODELS:
                    target = _OCR_ROOT / model_name
                    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha256:
                        continue
                    target.unlink(missing_ok=True)
                    temporary = target.with_suffix(target.suffix + ".part")
                    digest = hashlib.sha256()
                    downloaded = 0
                    _OCR_PROGRESS.update(detail=f"正在下载并校验本地 OCR 模型 {model_name}")
                    request = urllib.request.Request(url, headers={"User-Agent": "Atlas-local-OCR/1.0"})
                    try:
                        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
                            while block := response.read(256 * 1024):
                                downloaded += len(block)
                                if downloaded > limit:
                                    raise ValueError(f"{model_name} 超过 {limit // (1024 * 1024)} MiB 下载限制")
                                output.write(block)
                                digest.update(block)
                                _OCR_PROGRESS.update(progress=min(0.98, ocr_runtime_status()["downloaded_bytes"] / total_size))
                        if digest.hexdigest() != expected_sha256:
                            raise ValueError(f"{model_name} SHA-256 校验失败；为避免加载被替换模型，下载已拒绝")
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            except ImportError as exc:
                raise RuntimeError("OCR 运行依赖未安装；请重新安装 Atlas 后端依赖 rapidocr 与 onnxruntime") from exc
            _OCR_ENGINE = RapidOCR(params={
                "Global.model_root_dir": str(_OCR_ROOT),
                "Global.use_cls": False,
                "Det.model_type": ModelType.SMALL,
                "Det.ocr_version": OCRVersion.PPOCRV6,
                "Rec.model_type": ModelType.SMALL,
                "Rec.ocr_version": OCRVersion.PPOCRV6,
            })
        return _OCR_ENGINE


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
    """Ensure cached local RapidOCR and recognize English/Simplified Chinese."""
    match = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/]+={0,2})", data_url)
    if not match:
        return "", {"kind": "media_understanding", "name": f"image-{index + 1}", "extractor": "rapidocr-onnxruntime", "status": "invalid_image"}
    import base64

    try:
        payload = base64.b64decode(match.group(2), validate=True)
        if len(payload) > 20 * 1024 * 1024:
            raise ValueError("OCR 图片超过 20 MiB 限制")
        engine = _ensure_rapidocr()
        result = engine(payload)
        text = "\n".join(result.txts or ()).strip()[:MAX_EXTRACTED_CHARS]
        if text:
            _OCR_PROGRESS.update(state="ready", progress=1.0, detail="本地中英文 RapidOCR 模型已就绪")
    except Exception as exc:
        detail = str(exc).strip()
        _OCR_PROGRESS.update(state="failed", detail=f"本地 OCR 准备/识别失败：{type(exc).__name__}: {detail[:300]}")
        status = f"failed:{type(exc).__name__}" + (f": {detail[:300]}" if detail else "")
        return "", _audit(f"image-{index + 1}", match.group(1), payload if "payload" in locals() else b"", "rapidocr-onnxruntime", status)
    return text, _audit(f"image-{index + 1}", match.group(1), payload, "rapidocr-onnxruntime", "complete" if text else "no_text", len(text))


def media_context_block(audit: dict[str, Any], text: str) -> str:
    """Build transcript context with a reproducible source digest and extraction method."""
    if not text.strip():
        return ""
    return (
        f"--- Media text extraction: {audit.get('name')} | method={audit.get('extractor')} "
        f"| sha256={audit.get('sha256', 'unavailable')} | chars={len(text)} ---\n{text}"
    )
