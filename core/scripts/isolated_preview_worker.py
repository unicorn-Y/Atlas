"""Credential-free worker for static Office/PDF previews.

This process only reads the copied input in its private temporary directory. Office
packages are parsed as data; macros and embedded active content are never launched.
"""
from __future__ import annotations

import base64
import html
import json
import os
import subprocess
import sys
from pathlib import Path


def _document(body: str, note: str = "") -> str:
    banner = f'<p class="note">{html.escape(note)}</p>' if note else ""
    return ("<!doctype html><html><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><style>"
            "body{font:15px system-ui,sans-serif;max-width:1000px;margin:1.5rem auto;padding:0 1rem;color:#20242a}"
            "table{border-collapse:collapse;margin:1rem 0;width:100%}td{border:1px solid #bbb;padding:.4rem}"
            "img{max-width:100%;height:auto;display:block;margin:0 auto 1rem}.note{color:#795500;background:#fff4ce;padding:.6rem;border-radius:.4rem}"
            ".page{border-bottom:1px solid #bbb;padding:1rem 0}</style></head><body>" + banner + body + "</body></html>")


def _pdf(path: Path, temp: Path) -> tuple[str, str]:
    # Prefer pixel rendering through bundled Poppler when installed; otherwise present
    # extracted text as a readable HTML fallback instead of a blank PDF frame.
    renderer = sys.argv[3] if len(sys.argv) > 3 else ""
    if renderer:
        prefix = temp / "page"
        try:
            subprocess.run(
                [renderer, "-f", "1", "-l", "20", "-png", "-scale-to", "1400", str(path), str(prefix)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, check=True,
            )
            pages = sorted(temp.glob("page-*.png"))
            if pages:
                images = []
                for page in pages:
                    data = base64.b64encode(page.read_bytes()).decode("ascii")
                    images.append(f'<section class="page"><img alt="PDF {html.escape(page.stem)}" src="data:image/png;base64,{data}"></section>')
                return _document("".join(images), "隔离渲染最多显示前 20 页。" if len(pages) == 20 else ""), "pdf-image"
        except (OSError, subprocess.SubprocessError):
            pass
    from pypdf import PdfReader

    reader = PdfReader(str(path), strict=False)
    chunks = []
    for index, page in enumerate(reader.pages[:100], 1):
        text = page.extract_text() or "（此页没有可提取的文本）"
        chunks.append(f'<section class="page"><h2>第 {index} 页</h2><pre>{html.escape(text)}</pre></section>')
    if not chunks:
        raise ValueError("PDF 中没有可显示页面；可用外部程序打开。")
    note = "渲染器不可用，已降级为 PDF 文本提取预览。" + ("仅显示前 100 页。" if len(reader.pages) > 100 else "")
    return _document("".join(chunks), note), "pdf-text"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    source = Path(sys.argv[1]).resolve()
    suffix = sys.argv[2].casefold()
    try:
        package_dir = sys.argv[5] if len(sys.argv) > 5 else ""
        if package_dir:
            sys.path.insert(0, package_dir)
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(package_dir)
        if suffix == ".pdf":
            rendered, mode = _pdf(source, source.parent)
        else:
            # Import after narrowing argv; office.py uses static document parsers only.
            core = Path(__file__).resolve().parents[1]
            sys.path.insert(0, str(core))
            from atlas.office import render_office

            rendered, mode = render_office(source.read_bytes(), suffix), "office-html"
        output = json.dumps({"html": rendered, "mode": mode}, ensure_ascii=False)
        if len(sys.argv) > 4 and sys.argv[4]:
            Path(sys.argv[4]).write_text(output, encoding="utf-8")
        else:
            print(output)
        return 0
    except Exception as exc:
        output = json.dumps({"error": f"隔离渲染失败：{exc}"}, ensure_ascii=False)
        if len(sys.argv) > 4 and sys.argv[4]:
            Path(sys.argv[4]).write_text(output, encoding="utf-8")
        else:
            print(output)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
