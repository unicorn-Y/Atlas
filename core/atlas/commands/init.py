"""/init —— 确定性的 AGENTS.md 生成器(扫描 → 提案 → diff → 应用)。

质量标准与合并纪律移植自 NousResearch/hermes-agent 的
``hermes_cli/init_command.py::build_init_prompt``(MIT, (c) Nous Research):

- 质量标准:全文精炼(目标 <100 行,本文件每个会话都会被加载,每行都占上下文);
  命令必须是仓库清单里核实过的确切调用(package.json scripts、Makefile 目标、
  pyproject/Cargo/go 等清单),绝不凭空发明;不写"多写测试""遵循最佳实践"之类
  对任何仓库都成立的泛泛建议。
- 合并纪律:AGENTS.md 已存在时不重写、不重排人工内容——原样保留用户的措辞、
  章节和规则,只追加/刷新一个明确标记的 Atlas 托管区段。

扫描清单参考 OpenCode ``command/template/initialize.txt`` 的结构检查表
(语言构成 / 构建 / 测试 / lint / 入口文件),保持有界且确定:
不调模型、不联网,同一次扫描永远得到同一份结果。

托管区段用成对标记包裹::

    <!-- atlas:init managed begin -->
    ...(Atlas 生成并维护的内容)...
    <!-- atlas:init managed end -->

二次运行时托管区段重新生成,若扫描结果未变则提案 == 磁盘现状,diff 为空(幂等)。
"""

from __future__ import annotations

import difflib
import json
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from fastapi import HTTPException

__all__ = [
    "MANAGED_BEGIN",
    "MANAGED_END",
    "apply_proposal",
    "build_proposal",
    "compute_diff",
    "register_init_routes",
    "scan_workspace",
]

# ---------------------------------------------------------------------------
# 托管区段标记
# ---------------------------------------------------------------------------

MANAGED_BEGIN = "<!-- atlas:init managed begin -->"
MANAGED_END = "<!-- atlas:init managed end -->"

_MANAGED_RE = re.compile(
    re.escape(MANAGED_BEGIN) + r"[^\S\r\n]*\r?\n.*?\r?\n[^\S\r\n]*" + re.escape(MANAGED_END),
    re.DOTALL,
)

AGENTS_FILENAME = "AGENTS.md"

# 托管区段在人工内容之后固定空两行接上(确定性排版)。
_SECTION_GAP = "\n\n"


# ---------------------------------------------------------------------------
# 校验与文件读写
# ---------------------------------------------------------------------------


def _validated_workspace(workspace: str) -> Path:
    """规范化并校验 workspace:必须存在且是目录;否则抛中文 ValueError。"""
    raw = str(workspace or "").strip()
    if not raw:
        raise ValueError("workspace 不能为空,请先选择一个项目目录。")
    root = Path(raw).expanduser()
    if not root.is_absolute():
        root = Path(os.path.abspath(root))
    root = Path(os.path.normpath(str(root)))
    if not root.exists():
        raise ValueError(f"工作区目录不存在:{root}")
    if not root.is_dir():
        raise ValueError(f"工作区路径不是目录:{root}")
    return root


def _read_text_verbatim(path: Path) -> str | None:
    """读取文件原始文本:保留 \\r\\n 行尾,容忍 BOM;不存在返回 None。"""
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as fh:
            return fh.read()
    except OSError:
        return None


def _detect_eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


# ---------------------------------------------------------------------------
# 扫描(有界、确定性)
# ---------------------------------------------------------------------------

_SKIP_DIRS = frozenset({
    ".git", ".venv", "venv", "node_modules", "dist", "build", "out", "target",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".next", ".turbo", ".cache", "coverage", "site-packages", ".idea", ".vscode",
})

_BINARY_EXTS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svgz",
    ".pdf", ".zip", ".gz", ".tgz", ".tar", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a", ".lib",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp3", ".mp4", ".avi", ".mov", ".mkv", ".wav", ".flac",
    ".sqlite", ".sqlite3", ".db", ".pyc", ".pyd", ".class", ".jar", ".wasm",
    ".onnx", ".pt", ".pth", ".safetensors", ".gguf",
})

# 代码语言按扩展名归类(排除文档/配置/数据文件,保持语言构成可读)。
_LANG_BY_EXT = {
    ".py": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
    ".c": "C", ".h": "C",
    ".cpp": "C++", ".cc": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++",
    ".m": "Objective-C", ".mm": "Objective-C",
    ".scala": "Scala", ".dart": "Dart", ".lua": "Lua", ".zig": "Zig", ".nim": "Nim",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell",
    ".bat": "Batch", ".cmd": "Batch",
    ".sql": "SQL", ".r": "R", ".jl": "Julia", ".ex": "Elixir", ".exs": "Elixir",
    ".erl": "Erlang", ".hs": "Haskell", ".clj": "Clojure", ".vue": "Vue", ".svelte": "Svelte",
}

# 包管理器:精确文件名 → 名称(确定性顺序无关,输出前统一排序)。
_PACKAGE_MANAGER_FILES = {
    "package-lock.json": "npm",
    "npm-shrinkwrap.json": "npm",
    "pnpm-lock.yaml": "pnpm",
    "pnpm-workspace.yaml": "pnpm",
    "yarn.lock": "yarn",
    "bun.lockb": "bun",
    "poetry.lock": "poetry",
    "uv.lock": "uv",
    "Cargo.lock": "cargo",
    "go.sum": "go",
    "Gemfile.lock": "bundler",
    "composer.lock": "composer",
    "mix.lock": "mix",
}

_MAX_SCANNED_FILES = 5000

_SCRIPT_CATEGORIES = {
    "build_commands": ("build", "compile"),
    "test_commands": ("test",),
    "lint_commands": ("lint", "fmt", "format"),
    "typecheck_commands": ("typecheck", "type-check", "typecheck:watch", "tsc", "check-types"),
}

_MAKE_TARGET_CATEGORIES = {
    "build_commands": ("build", "compile", "all", "dist"),
    "test_commands": ("test", "tests"),
    "lint_commands": ("lint", "check", "fmt", "format"),
    "typecheck_commands": ("typecheck", "type-check"),
}

_ENTRYPOINT_CANDIDATES = (
    "main.py", "app.py", "manage.py", "src/main.py", "src/app.py",
    "index.js", "index.ts", "main.js", "main.ts", "src/index.js", "src/index.ts",
    "main.go", "src/main.rs", "src/main.kt", "app/main.py",
)

_MAX_COMMANDS_PER_CATEGORY = 8
_MAX_ENTRYPOINTS = 8


def _match_category(name: str, table: dict[str, tuple[str, ...]]) -> str | None:
    lowered = name.lower()
    for category, names in table.items():
        if lowered in names:
            return category
    return None


def _scan_package_json(root: Path, scan: dict[str, Any]) -> None:
    """从根目录 package.json 的 scripts 提取可核实命令(带来源标注)。"""
    path = root / "package.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    scripts = data.get("scripts")
    if not isinstance(scripts, dict):
        return
    for name in sorted(scripts, key=str):
        category = _match_category(str(name), _SCRIPT_CATEGORIES)
        if category is not None and len(scan[category]) < _MAX_COMMANDS_PER_CATEGORY:
            scan[category].append(f"npm run {name} (package.json)")
    main_field = data.get("main")
    if isinstance(main_field, str) and main_field.strip():
        main_rel = main_field.strip().replace("\\", "/")
        if (root / main_rel).is_file():
            scan["entrypoints"].append(main_rel)


def _scan_pyproject(root: Path, scan: dict[str, Any]) -> None:
    path = root / "pyproject.toml"
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    if "[tool.pytest" in text or re.search(r"(?m)^\s*pytest\s*=", text):
        if len(scan["test_commands"]) < _MAX_COMMANDS_PER_CATEGORY:
            scan["test_commands"].append("pytest (pyproject.toml)")
    if "[tool.ruff" in text:
        if len(scan["lint_commands"]) < _MAX_COMMANDS_PER_CATEGORY:
            scan["lint_commands"].append("ruff check . (pyproject.toml)")
    if "[tool.mypy" in text:
        if len(scan["typecheck_commands"]) < _MAX_COMMANDS_PER_CATEGORY:
            scan["typecheck_commands"].append("mypy . (pyproject.toml)")
    if "[build-system]" in text:
        if len(scan["build_commands"]) < _MAX_COMMANDS_PER_CATEGORY:
            scan["build_commands"].append("pip install -e . (pyproject.toml)")


def _scan_makefile(root: Path, scan: dict[str, Any], filename: str, runner: str) -> None:
    path = root / filename
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return
    for line in text.splitlines():
        if line[:1] in ("\t", " ", "#", ""):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9_-]*):", line)
        if not match:
            continue
        category = _match_category(match.group(1), _MAKE_TARGET_CATEGORIES)
        if category is not None and len(scan[category]) < _MAX_COMMANDS_PER_CATEGORY:
            scan[category].append(f"{runner} {match.group(1)} ({filename})")


def _scan_manifest_commands(root: Path, scan: dict[str, Any]) -> None:
    """Cargo / Go / Maven / Gradle 清单 → 官方固定命令(清单存在即视为核实)。"""
    entries = (
        ("Cargo.toml", (
            ("build_commands", "cargo build"),
            ("test_commands", "cargo test"),
            ("lint_commands", "cargo clippy"),
        )),
        ("go.mod", (
            ("build_commands", "go build ./..."),
            ("test_commands", "go test ./..."),
            ("lint_commands", "go vet ./..."),
        )),
        ("pom.xml", (
            ("build_commands", "mvn package"),
            ("test_commands", "mvn test"),
        )),
        ("build.gradle", (
            ("build_commands", "gradle build"),
            ("test_commands", "gradle test"),
        )),
        ("build.gradle.kts", (
            ("build_commands", "gradle build"),
            ("test_commands", "gradle test"),
        )),
    )
    for filename, commands in entries:
        if not (root / filename).is_file():
            continue
        for category, command in commands:
            if len(scan[category]) < _MAX_COMMANDS_PER_CATEGORY:
                scan[category].append(f"{command} ({filename})")


def scan_workspace(workspace: str) -> dict[str, Any]:
    """有界文件普查:语言构成(≤10)、包管理器、可核实命令、入口、既有规则文件。

    跳过 node_modules/.git/.venv/dist/build 等目录与二进制扩展名,最多扫描约
    5000 个文件。所有输出排序固定,保证确定性。
    """
    root = _validated_workspace(workspace)

    languages: dict[str, int] = {}
    managers: set[str] = set()
    scanned = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS)
        for filename in sorted(filenames):
            scanned += 1
            if scanned > _MAX_SCANNED_FILES:
                break
            if filename in _PACKAGE_MANAGER_FILES:
                managers.add(_PACKAGE_MANAGER_FILES[filename])
            ext = os.path.splitext(filename)[1].lower()
            language = _LANG_BY_EXT.get(ext)
            if language is not None:
                languages[language] = languages.get(language, 0) + 1
        if scanned > _MAX_SCANNED_FILES:
            break

    ranked = sorted(languages.items(), key=lambda item: (-item[1], item[0]))[:10]

    scan: dict[str, Any] = {
        "languages": [{"name": name, "count": count} for name, count in ranked],
        "package_managers": [],
        "build_commands": [],
        "test_commands": [],
        "lint_commands": [],
        "typecheck_commands": [],
        "entrypoints": [],
        "existing": {
            "AGENTS.md": (root / "AGENTS.md").is_file(),
            "CLAUDE.md": (root / "CLAUDE.md").is_file(),
            ".atlas/rules.md": (root / ".atlas" / "rules.md").is_file(),
        },
    }

    if (root / "requirements.txt").is_file() or (root / "requirements-dev.txt").is_file():
        managers.add("pip")
    if (root / "pyproject.toml").is_file() and not ({"poetry", "uv"} & managers):
        managers.add("pip")

    _scan_package_json(root, scan)
    _scan_pyproject(root, scan)
    _scan_makefile(root, scan, "Makefile", "make")
    _scan_makefile(root, scan, "justfile", "just")
    _scan_manifest_commands(root, scan)

    for entrypoint in _ENTRYPOINT_CANDIDATES:
        if len(scan["entrypoints"]) >= _MAX_ENTRYPOINTS:
            break
        if (root / entrypoint).is_file():
            scan["entrypoints"].append(entrypoint)

    scan["entrypoints"] = list(dict.fromkeys(scan["entrypoints"]))[:_MAX_ENTRYPOINTS]
    scan["package_managers"] = sorted(managers)
    return scan


# ---------------------------------------------------------------------------
# 提案生成(确定性;合并纪律:人工内容原样保留,只动托管区段)
# ---------------------------------------------------------------------------


def _managed_body(scan: dict[str, Any], eol: str = "\n") -> str:
    """按扫描结果生成托管区段正文(不含标记行);行尾跟随文件原有风格。"""
    lines: list[str] = []
    lines.append("# AGENTS.md")
    lines.append("")
    lines.append(
        "> 本区段由 Atlas `/init` 自动生成并维护;标记之外的人工内容不会被改动。"
    )
    lines.append("")
    lines.append("## 项目概览")
    lines.append("")
    languages = scan.get("languages") or []
    if languages:
        summary = "、".join(f"{item['name']} ×{item['count']}" for item in languages)
        lines.append(f"- 语言构成:{summary}")
    if scan.get("package_managers"):
        lines.append("- 包管理:" + "、".join(scan["package_managers"]))
    entrypoints = scan.get("entrypoints") or []
    if entrypoints:
        lines.append("- 入口文件:" + "、".join(f"`{path}`" for path in entrypoints))
    existing = scan.get("existing") or {}
    other_rules = [
        name for name in ("CLAUDE.md", ".atlas/rules.md") if existing.get(name)
    ]
    if other_rules:
        lines.append("- 其他规则文件:" + "、".join(f"`{name}`" for name in other_rules))
    lines.append("")
    lines.append("## 常用命令")
    lines.append("")
    labels = (
        ("build_commands", "构建"),
        ("test_commands", "测试"),
        ("lint_commands", "代码检查"),
        ("typecheck_commands", "类型检查"),
    )
    wrote_command = False
    for key, label in labels:
        for command in scan.get(key) or []:
            lines.append(f"- {label}:`{command}`")
            wrote_command = True
    if not wrote_command:
        lines.append("- 未在仓库清单中检测到可核实的命令,请按实际脚本补充,不要凭空猜测。")
    lines.append("")
    lines.append("## 注意事项")
    lines.append("")
    lines.append("- 命令均取自仓库清单(package.json / Makefile / pyproject.toml 等),未核实过的命令不要写入本文件。")
    lines.append("- 保持精炼(全文目标 <100 行):本文件每个会话都会被加载,每行都占上下文。")
    lines.append("- 不写泛泛建议:只记录本仓库独有的约定、可直接核实的事实与已知的坑。")
    return eol.join(lines)


def _compose(existing_raw: str | None, scan: dict[str, Any]) -> str:
    """合并纪律:无托管区段则追加,有则只重生成区段;人工内容逐字保留。"""
    if existing_raw is None:
        # 全新文件:整份内容都在托管标记内,保证二次运行天然幂等。
        body = _managed_body(scan, "\n")
        return f"{MANAGED_BEGIN}\n{body}\n{MANAGED_END}\n"
    eol = _detect_eol(existing_raw)
    body = _managed_body(scan, eol)
    managed = f"{MANAGED_BEGIN}{eol}{body}{eol}{MANAGED_END}"
    match = _MANAGED_RE.search(existing_raw)
    if match is None:
        human = existing_raw.rstrip("\r\n")
    else:
        human = existing_raw[: match.start()].rstrip("\r\n")
    if not human.strip():
        return managed + eol
    return human + eol + eol + managed + eol


def build_proposal(workspace: str) -> dict[str, Any]:
    """生成 AGENTS.md 提案;已有文件时只补缺/刷新 Atlas 托管区段。"""
    root = _validated_workspace(workspace)
    agents_path = root / AGENTS_FILENAME
    exists = agents_path.is_file()
    existing_content = _read_text_verbatim(agents_path) if exists else None
    scan = scan_workspace(str(root))
    proposed = _compose(existing_content, scan)
    return {
        "path": str(agents_path),
        "exists": exists,
        "existing_content": existing_content if existing_content is not None else "",
        "proposed_content": proposed,
        "scan": scan,
    }


def compute_diff(existing: str, proposed: str) -> str:
    """两份内容的 unified diff;完全一致时返回空字符串。"""
    if existing == proposed:
        return ""
    diff = difflib.unified_diff(
        existing.splitlines(),
        proposed.splitlines(),
        fromfile="AGENTS.md(当前)",
        tofile="AGENTS.md(提案)",
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# 应用(带并发竞态防护)
# ---------------------------------------------------------------------------


def apply_proposal(workspace: str, content: str, expected_existing: str | None) -> dict[str, Any]:
    """把提案写入 workspace/AGENTS.md,带竞态防护。

    磁盘当前内容与 ``expected_existing`` 不一致(None 表示"文件应当不存在")时
    拒绝写入并返回中文错误;成功时按 UTF-8 原样写入(content 自带行尾风格,
    覆盖已有文件时即保留其原有行尾)。目录不存在时返回错误,不静默建目录。
    """
    try:
        root = _validated_workspace(workspace)
    except ValueError as exc:
        return {"written": False, "error": str(exc)}
    agents_path = root / AGENTS_FILENAME
    current = _read_text_verbatim(agents_path) if agents_path.is_file() else None
    expected = None if expected_existing is None else str(expected_existing)
    if current != expected:
        return {"written": False, "error": "文件已被修改,请重新生成预览。"}
    try:
        with open(agents_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
    except OSError as exc:
        return {"written": False, "error": f"写入失败:{exc}"}
    return {"written": True, "path": str(agents_path)}


# ---------------------------------------------------------------------------
# FastAPI 路由(注册到主 app;OriginGuard 自动覆盖 /api)
# ---------------------------------------------------------------------------


class InitPreviewRequest(BaseModel):
    workspace: str


class InitApplyRequest(BaseModel):
    workspace: str
    content: str
    expected_existing: str | None = None


def register_init_routes(app: Any) -> None:
    """注册 POST /api/init/preview 与 POST /api/init/apply。"""

    @app.post("/api/init/preview")
    async def init_preview(payload: InitPreviewRequest) -> dict[str, Any]:
        try:
            proposal = build_proposal(payload.workspace)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        diff = compute_diff(proposal["existing_content"], proposal["proposed_content"])
        return {**proposal, "diff": diff}

    @app.post("/api/init/apply")
    async def init_apply(payload: InitApplyRequest) -> dict[str, Any]:
        result = apply_proposal(payload.workspace, payload.content, payload.expected_existing)
        if not result.get("written"):
            raise HTTPException(status_code=422, detail=str(result.get("error") or "写入失败"))
        return result
