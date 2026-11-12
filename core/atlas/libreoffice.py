"""Document conversion, reclaculation and rendering through LibreOffice.

``atlas.office`` already creates, reads and previews Office files. What it cannot
do is the three things that actually require a real office engine:

* **export to PDF** — the format people send to each other;
* **recalculate formulas** — an ``.xlsx`` written by openpyxl has *no* cached
  values, so every formula cell reads as empty until something opens it;
* **render to an image** — checking that a layout actually looks right.

LibreOffice's headless mode does all three. It is an optional dependency: the
machine may not have it. So every entry point reports ``available: False`` with
an actionable hint instead of raising, and formula recalculation degrades to a
pure-Python path when a formula engine is installed (``formulas`` or ``pycel``).

Why a subprocess and not UNO: ``soffice --headless --convert-to`` needs no
Python-version match, no Python bootstrap, and no long-lived listener. The
per-conversion cost (~1 s) is fine for a tool an agent calls occasionally, and a
crash cannot take the backend down with it. A persistent listener is deliberately
not used — it leaves a background process owning a profile directory, and Atlas
has a rule against unowned background processes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_TIMEOUT_SECONDS = 180

_CANDIDATES = (
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/local/bin/soffice",
    "/usr/bin/libreoffice",
)

#: Extension -> target it can be exported to. LibreOffice's own filter names are
#: used only where the plain extension is ambiguous.
_EXPORTABLE = {
    ".docx": "pdf",
    ".doc": "pdf",
    ".odt": "pdf",
    ".rtf": "pdf",
    ".xlsx": "pdf",
    ".xls": "pdf",
    ".ods": "pdf",
    ".pptx": "pdf",
    ".ppt": "pdf",
    ".odp": "pdf",
    ".csv": "pdf",
}

_RENDERABLE = (".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp")


def find_soffice() -> str | None:
    """Locate the LibreOffice binary, honoring an explicit override first."""
    override = os.environ.get("ATLAS_SOFFICE") or os.environ.get("SOFFICE_PATH")
    if override:
        candidate = Path(override)
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for raw in _CANDIDATES:
        candidate = Path(raw)
        if candidate.is_file():
            return str(candidate)
    return None


def is_available() -> bool:
    return find_soffice() is not None


def status() -> dict[str, Any]:
    """What this module can do on this machine right now."""
    binary = find_soffice()
    engine = _formula_engine()
    return {
        "available": binary is not None,
        "binary": binary,
        "formula_engine": engine,
        "can_export_pdf": binary is not None,
        "can_recalculate": binary is not None or engine is not None,
        "can_render": binary is not None,
        "hint": (
            None
            if binary
            else "未安装 LibreOffice：设置 ATLAS_SOFFICE 指向 soffice.exe，"
            "或从 https://www.libreoffice.org/download/ 安装后重试。"
        ),
    }


def _formula_engine() -> str | None:
    for name in ("formulas", "pycel"):
        try:
            __import__(name)
            return name
        except Exception as exc:  # noqa: BLE001 - optional dependency probe
            log.debug("libreoffice.formula_engine_absent", module=name, error=str(exc))
            continue
    return None


def _run(
    arguments: list[str], *, timeout: int = _TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """Run soffice without inheriting Atlas credentials into its environment."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "HOME",
            "USERPROFILE",
            "LANG",
            "LC_ALL",
        }
    }
    # Each conversion gets a throwaway profile: a shared one deadlocks when two
    # conversions run at once, which is exactly what parallel tool calls do.
    with tempfile.TemporaryDirectory(prefix="atlas-lo-profile-") as profile:
        env["HOME"] = profile
        env["USERPROFILE"] = profile
        command = [*arguments[:1], f"-env:UserInstallation=file:///{profile.replace(os.sep, '/')}",
                   *arguments[1:]] if arguments else arguments
        return subprocess.run(  # noqa: S603 - fixed binary, argument list, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            check=False,
        )


def convert(source: str, *, target: str = "pdf", out_dir: str | None = None) -> dict[str, Any]:
    """Convert ``source`` to ``target`` and return the produced file.

    ``target`` is a LibreOffice filter extension: ``pdf``, ``docx``, ``xlsx``,
    ``csv``, ``png``.
    """
    path = Path(source)
    if not path.is_file():
        return {"ok": False, "error": f"文件不存在：{source}"}

    binary = find_soffice()
    if binary is None:
        return {
            "ok": False,
            "error": "未安装 LibreOffice，无法转换。",
            **status(),
        }

    destination = Path(out_dir) if out_dir else path.parent
    destination.mkdir(parents=True, exist_ok=True)

    try:
        completed = _run(
            [binary, "--headless", "--norestore", "--convert-to", target,
             "--outdir", str(destination), str(path)]
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"转换超时（>{_TIMEOUT_SECONDS}s）"}
    except OSError as exc:
        return {"ok": False, "error": f"启动 LibreOffice 失败：{exc}"}

    produced = destination / f"{path.stem}.{target}"
    if not produced.is_file():
        detail = (completed.stderr or completed.stdout or "").strip()[:400]
        return {
            "ok": False,
            "error": "LibreOffice 没有产出文件。",
            "exit_code": completed.returncode,
            "detail": detail,
        }
    return {
        "ok": True,
        "source": str(path),
        "path": str(produced),
        "bytes": produced.stat().st_size,
        "target": target,
    }


def export_pdf(source: str, *, out_dir: str | None = None) -> dict[str, Any]:
    """Export a Word/Excel/PowerPoint file to PDF."""
    suffix = Path(source).suffix.lower()
    if suffix not in _EXPORTABLE:
        return {
            "ok": False,
            "error": f"不支持导出为 PDF 的类型：{suffix or '（无扩展名）'}",
            "supported": sorted(_EXPORTABLE),
        }
    return convert(source, target="pdf", out_dir=out_dir)


def render(source: str, *, page: int = 1, out_dir: str | None = None) -> dict[str, Any]:
    """Render one page/slide of a document to PNG for visual checking."""
    path = Path(source)
    if path.suffix.lower() not in _RENDERABLE:
        return {
            "ok": False,
            "error": f"不支持渲染的类型：{path.suffix or '（无扩展名）'}",
            "supported": list(_RENDERABLE),
        }

    # Rendering a document page needs PDF as a hop for non-PDF inputs: LibreOffice
    # exports the whole document to PDF, then a single page is rasterised.
    with tempfile.TemporaryDirectory(prefix="atlas-lo-render-") as scratch:
        pdf_source = path
        if path.suffix.lower() != ".pdf":
            exported = export_pdf(str(path), out_dir=scratch)
            if not exported.get("ok"):
                return exported
            pdf_source = Path(exported["path"])

        destination = Path(out_dir) if out_dir else path.parent
        destination.mkdir(parents=True, exist_ok=True)
        target = destination / f"{path.stem}-p{page}.png"

        rasteriser = _rasteriser()
        if rasteriser is None:
            return {
                "ok": False,
                "error": "缺少把 PDF 转成图片的工具（pdftoppm 或 PyMuPDF）。",
                "binary": find_soffice(),
            }
        command, kind = rasteriser
        if kind == "pdftoppm":
            result = subprocess.run(  # noqa: S603 - fixed binary, argument list
                [*command, "-f", str(page), "-l", str(page), "-png", "-singlefile",
                 str(pdf_source), str(target.with_suffix(""))],
                capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False,
            )
            if not target.is_file():
                return {"ok": False, "error": "pdftoppm 没有产出图片。",
                        "detail": (result.stderr or "")[:300]}
        else:
            import fitz  # PyMuPDF

            with fitz.open(str(pdf_source)) as document:
                if not 1 <= page <= document.page_count:
                    return {"ok": False, "error": f"页码超出范围（1..{document.page_count}）"}
                pixmap = document[page - 1].get_pixmap()
                pixmap.save(str(target))
        return {"ok": True, "path": str(target), "bytes": target.stat().st_size, "page": page}


def _rasteriser() -> tuple[list[str], str] | None:
    binary = shutil.which("pdftoppm")
    if binary:
        return ([binary], "pdftoppm")
    try:
        import fitz  # noqa: F401

        return ([], "pymupdf")
    except Exception:  # noqa: BLE001 - optional dependency probe
        return None


def recalculate(source: str, *, out_dir: str | None = None) -> dict[str, Any]:
    """Force LibreOffice to recompute formulas and save the cached values.

    This is the one operation with no pure-Python substitute for arbitrary
    workbooks: ``openpyxl`` reads the *cached* value, and a file written by
    ``openpyxl`` has none. Opening and re-saving in LibreOffice fills them in.
    """
    path = Path(source)
    if not path.is_file():
        return {"ok": False, "error": f"文件不存在：{source}"}
    if path.suffix.lower() not in {".xlsx", ".xls", ".ods", ".csv"}:
        return {"ok": False, "error": "只有表格文件需要重算。"}

    binary = find_soffice()
    if binary is None:
        return _recalculate_with_formulas(path, out_dir=out_dir)

    destination = Path(out_dir) if out_dir else path.parent
    destination.mkdir(parents=True, exist_ok=True)

    # Converting xlsx -> xlsx in place is rejected by LibreOffice, so round-trip
    # through ods in a scratch dir and convert back. Both steps recompute.
    with tempfile.TemporaryDirectory(prefix="atlas-lo-recalc-") as scratch:
        first = convert(str(path), target="ods", out_dir=scratch)
        if not first.get("ok"):
            return first
        second = convert(first["path"], target=path.suffix.lstrip("."), out_dir=str(destination))
        if not second.get("ok"):
            return second
        return {
            "ok": True,
            "path": second["path"],
            "bytes": second["bytes"],
            "recalculated_by": "libreoffice",
        }


def _recalculate_with_formulas(path: Path, *, out_dir: str | None = None) -> dict[str, Any]:
    """Fallback recompute using the pure-Python ``formulas`` engine.

    LibreOffice is the correct tool for this, but it is a ~400 MB install. When it
    is absent this path still fills in the caches so ``openpyxl`` (and anything
    else reading cached values) sees numbers instead of ``None``. ``formulas``
    models the workbook as a dependency graph and evaluates it, which is exactly
    the semantics we want — the tradeoff is a slower start and coverage that is
    good but not identical to LibreOffice for exotic functions.
    """
    engine = _formula_engine()
    if engine != "formulas":
        if engine is None:
            return {
                "ok": False,
                "error": "重算需要 LibreOffice 或 formulas，当前都没有。",
                **status(),
            }
        return {"ok": False, "error": f"检测到 {engine}，但它不能写回缓存值；请安装 LibreOffice。"}

    try:
        import formulas
    except Exception as exc:  # noqa: BLE001 - optional dependency
        return {"ok": False, "error": f"formulas 导入失败：{exc}"}

    destination = Path(out_dir) if out_dir else path.parent
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / f"{path.stem}-recalculated{path.suffix}"

    try:
        workbook = formulas.ExcelModel().loads(str(path)).finish()
        # ``calculate`` returns the solved cell map; ``write`` persists it.
        workbook.calculate()
        workbook.write(dirpath=str(destination), filename=target.name)
    except Exception as exc:  # noqa: BLE001 - a bad workbook must not crash the tool
        return {"ok": False, "error": f"formulas 重算失败：{type(exc).__name__}: {exc}"}

    if not target.is_file():
        return {"ok": False, "error": "formulas 没有写出文件。"}
    return {
        "ok": True,
        "path": str(target),
        "bytes": target.stat().st_size,
        "recalculated_by": "formulas",
    }


def describe() -> dict[str, Any]:
    """Tool-facing capability summary."""
    return status()
