#!/usr/bin/env python3
"""Read-only DSH source inventory and auditable semantic-coverage ledger."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from collections import Counter
from typing import Any


PINNED_DSH_COMMIT = "d743267388641bc76f17c45ce8b4c231aed1d32c"
EXTRACTOR_VERSION = 19
TYPESCRIPT_SUFFIXES = {".js", ".jsx", ".mjs", ".mts", ".ts", ".tsx"}
CODE_SUFFIXES = {
    ".c", ".cc", ".cmd", ".cpp", ".cs", ".css", ".go", ".h", ".hpp", ".java", ".js", ".jsx",
    ".mjs", ".mts", ".nsh", ".nsi", ".ps1", ".py", ".rb", ".rs", ".sh", ".sql", ".swift", ".ts", ".tsx",
    ".vue", ".yaml", ".yml", ".json", ".toml",
}
EXPORT_RE = re.compile(
    r"^\s*export\s+(?:(?:declare|default|abstract|async)\s+)*(?:function|class|interface|type|enum|const|let|var)\s+([\w$]+)"
)
PY_DECL_RE = re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)")
JS_FUNC_RE = re.compile(r"^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)\s*\(")
TS_DECL_RE = re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][\w$]*)\s*\([^;{}]*\)\s*(?::[^={]+)?\s*[{:;]?")
PLATFORM_RE = re.compile(
    r"(?:process\.platform|process\.arch|sys\.platform|os\.name|platform\.system\s*\(|Platform\.OS|isWindows|isMacOS|isLinux)"
)
STATE_RE = re.compile(r"\b(?:case\s+['\"]|transition\s*\(|status\s*[:=]|phase\s*[:=]|State\.[A-Z_]+)")
PROTOCOL_RE = re.compile(
    r"(?:['\"](?:session|approval|input|tools|initialize|shutdown|websocket)[./][A-Za-z0-9_./-]+['\"]|\bmethod\s*[:=])"
)
DEFAULT_RE = re.compile(r"\b(?:default|defaultValue|default_value|DEFAULT_[A-Z0-9_]+)\b")
IMPORT_RE = re.compile(r"^\s*(?:import\s|from\s+\S+\s+import\s|require\s*\(|use\s+)")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git_paths(root: Path) -> tuple[str | None, list[str]]:
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        raw = subprocess.run(
            ["git", "ls-files", "-z"], cwd=root, check=True,
            capture_output=True, timeout=30,
        ).stdout
        paths = [item.decode("utf-8", errors="surrogateescape") for item in raw.split(b"\0") if item]
        return head, sorted(paths)
    except (OSError, subprocess.SubprocessError):
        return None, []


def _filesystem_paths(root: Path) -> list[str]:
    paths: list[str] = []
    for directory, names, files in os.walk(root):
        names[:] = sorted(name for name in names if name not in {".git", "node_modules", ".venv", "__pycache__"})
        for name in files:
            path = Path(directory, name)
            if not path.is_symlink():
                paths.append(path.relative_to(root).as_posix())
    return sorted(paths)


def _classify(path: str) -> str:
    parts = {part.casefold() for part in Path(path).parts}
    name = Path(path).name.casefold()
    suffix = Path(path).suffix.casefold()
    if parts & {"vendor", "third_party", "third-party", "externals"}:
        return "vendor"
    if (parts & {"test", "tests", "__tests__", "fixtures", "fixture"}
            or name.endswith((".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx"))):
        return "test"
    if parts & {"docs", "doc", "documentation"} or suffix in {".md", ".mdx", ".rst"}:
        return "documentation"
    if any(token in name for token in (".generated.", ".gen.", ".g.", "_generated")):
        return "generated"
    if name in {"package.json", "tsconfig.json", "pyproject.toml"}:
        return "manifest"
    if suffix in CODE_SUFFIXES:
        return "source"
    return "resource"


def _component_for(path: str, package_roots: dict[str, str]) -> str | None:
    if path == "package.json" and "." in package_roots:
        return package_roots["."]
    candidates = [root for root in package_roots if path == root or path.startswith(root + "/")]
    if not candidates:
        return None
    return package_roots[max(candidates, key=len)]


def _scope_for(path: str, component_id: str | None) -> str:
    """Assign accountable ownership without promoting repo files into packages."""
    if component_id:
        return f"component:{component_id}"
    parts = Path(path).parts
    root = parts[0] if len(parts) > 1 else "root"
    return f"repository:{root}"


def _unit_id(path: str, kind: str, symbol: str, text: str, ordinal: int) -> str:
    normalized = re.sub(r"\s+", " ", text.strip())
    identity = "\0".join((path, kind, symbol, normalized, str(ordinal)))
    return "DSH-" + hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:20].upper()


def _python_function_contracts(text: str, tree: ast.AST) -> dict[int, dict[str, Any]]:
    contracts: dict[int, dict[str, Any]] = {}
    lines = text.splitlines()
    os_modules: set[str] = set()
    getenv_names: set[str] = set()
    environ_names: set[str] = set()
    for imported in ast.walk(tree):
        if isinstance(imported, ast.Import):
            for alias in imported.names:
                if alias.name == "os":
                    os_modules.add(alias.asname or "os")
        elif isinstance(imported, ast.ImportFrom) and imported.module == "os":
            for alias in imported.names:
                if alias.name == "getenv":
                    getenv_names.add(alias.asname or alias.name)
                elif alias.name == "environ":
                    environ_names.add(alias.asname or alias.name)

    def scoped_nodes(root: ast.AST):
        stack = list(reversed(list(ast.iter_child_nodes(root))))
        while stack:
            node = stack.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            yield node
            stack.extend(reversed(list(ast.iter_child_nodes(node))))

    def visit(node: ast.AST, names: tuple[str, ...], class_names: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, (*names, child.name), (*class_names, child.name))
                continue
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = child.args
                positional = [*args.posonlyargs, *args.args]
                positional_defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
                parameters = []
                for argument, default in zip(positional, positional_defaults):
                    expression = ast.get_source_segment(text, default) if default is not None else None
                    parameters.append({
                        "name": argument.arg,
                        "default_digest": _sha(expression.encode("utf-8")) if expression is not None else None,
                    })
                for argument, default in zip(args.kwonlyargs, args.kw_defaults):
                    expression = ast.get_source_segment(text, default) if default is not None else None
                    parameters.append({
                        "name": argument.arg,
                        "default_digest": _sha(expression.encode("utf-8")) if expression is not None else None,
                    })
                exceptions = []
                exception_scopes = []
                raises = []
                await_error_sites = []
                resource_scopes = []
                platforms = []
                transitions = []
                configuration_reads = []

                def node_span(item: ast.AST | None) -> dict[str, int] | None:
                    if item is None:
                        return None
                    start = int(getattr(item, "lineno", 0) or 0)
                    end = int(getattr(item, "end_lineno", start) or start)
                    return {"start_line": start, "end_line": end}

                def statements_span(items: list[ast.stmt]) -> dict[str, int] | None:
                    if not items:
                        return None
                    return {
                        "start_line": int(getattr(items[0], "lineno", 0) or 0),
                        "end_line": int(getattr(items[-1], "end_lineno", getattr(items[-1], "lineno", 0)) or 0),
                    }

                for item in scoped_nodes(child):
                    if isinstance(item, ast.ExceptHandler):
                        if item.type is None:
                            exception_type = "<bare-except>"
                        else:
                            exception_type = ast.unparse(item.type)
                        exceptions.append({"type": exception_type, "line": item.lineno})
                    try_node_types = (ast.Try,)
                    if hasattr(ast, "TryStar"):
                        try_node_types = (*try_node_types, ast.TryStar)
                    if isinstance(item, try_node_types):
                        handlers = []
                        for handler in item.handlers:
                            exception_type = ast.unparse(handler.type) if handler.type is not None else None
                            handlers.append({
                                "handler_kind": "except_star" if isinstance(item, getattr(ast, "TryStar", ())) else "except",
                                "source_span": node_span(handler),
                                "exception_type_digest": _sha(exception_type.encode("utf-8"))
                                    if exception_type is not None else None,
                                "body_digest": _sha("\n".join(
                                    ast.get_source_segment(text, statement) or ast.unparse(statement)
                                    for statement in handler.body
                                ).encode("utf-8")),
                            })
                        exception_scopes.append({
                            "try_span": statements_span(item.body),
                            "handlers": handlers,
                            "else_span": statements_span(item.orelse),
                            "finally_span": statements_span(item.finalbody),
                            "try_body_digest": _sha("\n".join(
                                ast.get_source_segment(text, statement) or ast.unparse(statement)
                                for statement in item.body
                            ).encode("utf-8")),
                            "else_body_digest": _sha("\n".join(
                                ast.get_source_segment(text, statement) or ast.unparse(statement)
                                for statement in item.orelse
                            ).encode("utf-8")) if item.orelse else None,
                            "finally_body_digest": _sha("\n".join(
                                ast.get_source_segment(text, statement) or ast.unparse(statement)
                                for statement in item.finalbody
                            ).encode("utf-8")) if item.finalbody else None,
                        })
                    if isinstance(item, ast.Raise):
                        raise_text = ast.get_source_segment(text, item.exc) if item.exc is not None else None
                        cause_text = ast.get_source_segment(text, item.cause) if item.cause is not None else None
                        raises.append({
                            "line": item.lineno,
                            "expression_digest": _sha(raise_text.encode("utf-8")) if raise_text is not None else None,
                            "cause_digest": _sha(cause_text.encode("utf-8")) if cause_text is not None else None,
                            "bare_reraise": item.exc is None,
                        })
                    if isinstance(item, ast.Await):
                        expression = ast.get_source_segment(text, item.value) or ast.unparse(item.value)
                        await_error_sites.append({
                            "kind": "await_rejection_candidate",
                            "line": item.lineno,
                            "expression_digest": _sha(expression.encode("utf-8")),
                        })
                    if isinstance(item, (ast.With, ast.AsyncWith)):
                        resource_scopes.append({
                            "kind": "async_with" if isinstance(item, ast.AsyncWith) else "with",
                            "source_span": node_span(item),
                            "items": [{
                                "context_expression_digest": _sha(
                                    (ast.get_source_segment(text, part.context_expr) or ast.unparse(part.context_expr))
                                    .encode("utf-8")
                                ),
                                "target_digest": _sha(
                                    (ast.get_source_segment(text, part.optional_vars) or ast.unparse(part.optional_vars))
                                    .encode("utf-8")
                                ) if part.optional_vars is not None else None,
                            } for part in item.items],
                        })
                    if isinstance(item, ast.If):
                        expression = ast.get_source_segment(text, item.test) or ast.unparse(item.test)
                        if PLATFORM_RE.search(expression):
                            platforms.append({"expression_digest": _sha(expression.encode("utf-8")),
                                              "line": item.lineno})
                    targets: list[ast.expr] = []
                    value: ast.expr | None = None
                    if isinstance(item, (ast.Assign, ast.AnnAssign)):
                        targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                        value = item.value
                    elif isinstance(item, ast.AugAssign):
                        targets = [item.target]
                        value = item.value
                    if value is not None:
                        for target in targets:
                            target_name = ast.unparse(target)
                            if re.search(r"(?:^|\.)(?:state|status|phase)$", target_name, re.IGNORECASE):
                                expression = ast.get_source_segment(text, value) or ast.unparse(value)
                                transitions.append({
                                    "target": target_name,
                                    "value_digest": _sha(expression.encode("utf-8")),
                                    "line": item.lineno,
                                })
                    environment_kind = None
                    key_node: ast.expr | None = None
                    fallback_node: ast.expr | None = None
                    if isinstance(item, ast.Call):
                        function = item.func
                        is_os_getenv = (
                            isinstance(function, ast.Attribute) and function.attr == "getenv"
                            and isinstance(function.value, ast.Name) and function.value.id in os_modules
                        )
                        is_imported_getenv = isinstance(function, ast.Name) and function.id in getenv_names
                        is_environ_get = (
                            isinstance(function, ast.Attribute) and function.attr == "get"
                            and isinstance(function.value, ast.Attribute) and function.value.attr == "environ"
                            and isinstance(function.value.value, ast.Name)
                            and function.value.value.id in os_modules
                        ) or (
                            isinstance(function, ast.Attribute) and function.attr == "get"
                            and isinstance(function.value, ast.Name) and function.value.id in environ_names
                        )
                        if (is_os_getenv or is_imported_getenv or is_environ_get) and item.args:
                            environment_kind = "call"
                            key_node = item.args[0]
                            fallback_node = item.args[1] if len(item.args) > 1 else None
                    elif isinstance(item, ast.Subscript):
                        base = item.value
                        is_os_environ = (
                            isinstance(base, ast.Attribute) and base.attr == "environ"
                            and isinstance(base.value, ast.Name) and base.value.id in os_modules
                        )
                        is_imported_environ = isinstance(base, ast.Name) and base.id in environ_names
                        if is_os_environ or is_imported_environ:
                            environment_kind = "subscript"
                            key_node = item.slice
                    if environment_kind:
                        key = key_node.value if isinstance(key_node, ast.Constant) and isinstance(key_node.value, str) else None
                        fallback_text = ast.get_source_segment(text, fallback_node) if fallback_node is not None else None
                        configuration_reads.append({
                            "source_kind": "environment",
                            "key": key,
                            "line": getattr(item, "lineno", 0),
                            "resolution": "resolved_environment_key" if key else "dynamic_environment_key_unresolved",
                            **({"fallback_kind": "call_default_argument",
                                "fallback_digest": _sha(fallback_text.encode("utf-8"))}
                               if fallback_text is not None else {}),
                        })
                qualname = ".".join((*names, child.name))
                owner = ".".join(class_names) if class_names else None
                contracts[child.lineno] = {
                    "kind": "python_method" if class_names else "python_function",
                    "qualname": qualname,
                    "owner": owner,
                    "async": isinstance(child, ast.AsyncFunctionDef),
                    "source_span": {"start_line": child.lineno, "end_line": child.end_lineno or child.lineno},
                    "parameters": parameters,
                    "obligations": {
                        "exceptions": sorted(exceptions, key=lambda row: (row["line"], row["type"])),
                        "exception_scopes": sorted(exception_scopes, key=lambda row: (row["try_span"] or {}).get("start_line", 0)),
                        "raises": sorted(raises, key=lambda row: row["line"]),
                        "await_error_sites": sorted(await_error_sites, key=lambda row: row["line"]),
                        "resource_scopes": sorted(resource_scopes, key=lambda row: (row["source_span"] or {}).get("start_line", 0)),
                        "platform_branches": sorted(platforms, key=lambda row: row["line"]),
                        "state_transitions": sorted(transitions, key=lambda row: row["line"]),
                    },
                    "configuration_reads": sorted(configuration_reads,
                                                   key=lambda row: (row["line"], row.get("key") or "")),
                }
                visit(child, (*names, child.name), class_names)

    visit(tree, (), ())
    return contracts


def _configuration_field_units(path: str, text: str) -> list[dict[str, Any]]:
    suffix = Path(path).suffix.casefold()
    parts = {part.casefold() for part in Path(path).parts}
    name = Path(path).name.casefold()
    is_config_json = suffix == ".json" and (
        bool(parts & {"config", "configs", "configuration", "settings"})
        or any(token in name for token in ("config", "settings", "preferences", "policy"))
    )
    if not (is_config_json or suffix in {".toml", ".yaml", ".yml"}):
        return []

    fields: list[tuple[str, int, str, str]] = []
    if is_config_json:
        decoder = json.JSONDecoder()
        position = 0

        def skip_space() -> None:
            nonlocal position
            while position < len(text) and text[position].isspace():
                position += 1

        def visit(prefix: tuple[str, ...] = ()) -> None:
            nonlocal position
            skip_space()
            start = position
            if position >= len(text):
                raise json.JSONDecodeError("missing value", text, position)
            if text[position] == "{":
                position += 1
                skip_space()
                if position < len(text) and text[position] == "}":
                    position += 1
                    return
                while True:
                    skip_space()
                    key, position = decoder.raw_decode(text, position)
                    if not isinstance(key, str):
                        raise json.JSONDecodeError("object key is not a string", text, position)
                    skip_space()
                    if position >= len(text) or text[position] != ":":
                        raise json.JSONDecodeError("missing object separator", text, position)
                    position += 1
                    visit((*prefix, key))
                    skip_space()
                    if position < len(text) and text[position] == ",":
                        position += 1
                        continue
                    if position < len(text) and text[position] == "}":
                        position += 1
                        return
                    raise json.JSONDecodeError("unterminated object", text, position)
            if text[position] == "[":
                position += 1
                skip_space()
                if position < len(text) and text[position] == "]":
                    position += 1
                    return
                index = 0
                while True:
                    visit((*prefix, str(index)))
                    index += 1
                    skip_space()
                    if position < len(text) and text[position] == ",":
                        position += 1
                        continue
                    if position < len(text) and text[position] == "]":
                        position += 1
                        return
                    raise json.JSONDecodeError("unterminated array", text, position)
            value, position = decoder.raw_decode(text, position)
            if prefix:
                fields.append((".".join(prefix), text.count("\n", 0, start) + 1,
                               type(value).__name__, text[start:position]))

        try:
            visit()
            skip_space()
            if position != len(text):
                raise json.JSONDecodeError("trailing data", text, position)
        except json.JSONDecodeError:
            return []
    else:
        section: list[str] = []
        yaml_sections: list[tuple[int, str]] = []
        yaml_indices: Counter[tuple[int, tuple[str, ...]]] = Counter()
        for line_number, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//")):
                continue
            if suffix in {".yaml", ".yml"}:
                indent = len(line) - len(line.lstrip(" "))
                while yaml_sections and yaml_sections[-1][0] >= indent:
                    yaml_sections.pop()
                prefix = tuple(yaml_sections[-1][1].split(".")) if yaml_sections else ()
                if stripped.startswith("-"):
                    item = stripped[1:].strip()
                    index_key = (indent, prefix)
                    index = yaml_indices[index_key]
                    yaml_indices[index_key] += 1
                    item_path = (*prefix, str(index))
                    yaml_sections.append((indent, ".".join(item_path)))
                    if ":" not in item:
                        value_type = "string" if item[:1] in {"'", '"'} else "expression"
                        fields.append((".".join(item_path), line_number, value_type, item))
                        continue
                    key, raw_value = item.split(":", 1)
                    key = key.strip().strip('"\'')
                    raw_value = raw_value.split("#", 1)[0].strip()
                    if not raw_value:
                        yaml_sections.append((indent + 1, ".".join((*item_path, key))))
                        continue
                    field_path = (*item_path, key)
                else:
                    if ":" not in stripped:
                        continue
                    key, raw_value = stripped.split(":", 1)
                    key = key.strip().strip('"\'')
                    raw_value = raw_value.split("#", 1)[0].strip()
                    if not key:
                        continue
                    if not raw_value:
                        yaml_sections.append((indent, ".".join((*prefix, key))))
                        continue
                    field_path = (*prefix, key)
                if not key:
                    continue
                if raw_value.startswith(("&", "*", "|", ">")):
                    continue
                value_type = "string" if raw_value[:1] in {"'", '"'} else (
                    "boolean" if raw_value.casefold() in {"true", "false"}
                    else "null" if raw_value.casefold() in {"null", "~"}
                    else "integer" if re.fullmatch(r"[-+]?\d+", raw_value)
                    else "number" if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw_value)
                    else "array" if raw_value.startswith("[")
                    else "object" if raw_value.startswith("{")
                    else "expression"
                )
                fields.append((".".join(field_path), line_number, value_type, raw_value))
                continue
            table = re.match(r"^\[([^\]]+)\]$", stripped) if suffix == ".toml" else None
            if table:
                section = [part.strip().strip('"\'') for part in table.group(1).split(".")]
                continue
            separator = "=" if suffix == ".toml" else ":"
            if separator not in stripped:
                continue
            key, raw_value = stripped.split(separator, 1)
            key = key.strip().strip('"\'')
            raw_value = raw_value.split("#", 1)[0].strip()
            if not key or not raw_value or raw_value.startswith(("-", "&", "*", "|", ">")):
                continue
            value_type = "string" if raw_value[:1] in {"'", '"'} else (
                "boolean" if raw_value.casefold() in {"true", "false"}
                else "integer" if re.fullmatch(r"[-+]?\d+", raw_value)
                else "number" if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", raw_value)
                else "array" if raw_value.startswith("[")
                else "object" if raw_value.startswith("{")
                else "expression"
            )
            fields.append((".".join([*section, key]), line_number, value_type, raw_value))

    result = []
    for ordinal, (field_path, line_number, value_type, value) in enumerate(fields):
        digest = _sha(value.encode("utf-8", errors="replace"))
        result.append({
            "unit_id": _unit_id(path, "configuration_field", field_path, field_path, ordinal),
            "path": path,
            "symbol": field_path,
            "kind": "configuration_field",
            "line": line_number,
            "digest": digest,
            "contract": {
                "field_path": field_path,
                "source_line": line_number,
                "value_type": value_type,
                "value_digest": digest,
            },
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
        })
    return result


def _typescript_function_contracts(
    root: Path, contents: dict[str, bytes], typescript_module: str | Path | None = None,
) -> dict[str, dict[str, Any]]:
    paths = [
        relative for relative in contents
        if Path(relative).suffix.casefold() in TYPESCRIPT_SUFFIXES
    ]
    if not paths:
        return {}
    json_configs: dict[str, list[str]] = {}
    for relative, data in contents.items():
        if Path(relative).suffix.casefold() != ".json":
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        fields = _configuration_field_units(relative, text)
        if fields:
            json_configs[relative] = [str(item["contract"]["field_path"]) for item in fields]

    candidates = [Path(typescript_module)] if typescript_module else []
    configured = os.environ.get("ATLAS_DSH_TYPESCRIPT_MODULE")
    if configured:
        candidates.append(Path(configured))
    candidates.extend((
        root / "node_modules" / "typescript" / "lib" / "typescript.js",
        Path(__file__).resolve().parents[2] / "node_modules" / "typescript" / "lib" / "typescript.js",
    ))
    typescript_module = next((item.resolve() for item in candidates if item.is_file()), None)
    if typescript_module is None:
        return {
            relative: {"path": relative, "contracts": [], "parse_diagnostics": [],
                       "parser_status": "MISSING_TYPESCRIPT_COMPILER"}
            for relative in paths
        }

    helper = Path(__file__).with_name("dsh_ts_contracts.cjs")
    try:
        completed = subprocess.run(
            ["node", "--max-old-space-size=8192", str(helper), str(typescript_module), str(root)],
            input=json.dumps({"source_paths": paths, "json_configs": json_configs}),
            capture_output=True, text=True, check=False, timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"TypeScript AST extraction could not run ({type(exc).__name__}).") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"TypeScript AST extraction failed closed (node exit {completed.returncode}; "
            f"stderr sha256 {_sha(completed.stderr.encode('utf-8', errors='replace'))}; "
            f"diagnostic {completed.stderr[:500].strip()!r})."
        )
    try:
        rows = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("TypeScript AST extractor returned invalid JSON; scan is incomplete.") from exc
    if not isinstance(rows, list):
        raise RuntimeError("TypeScript AST extractor returned a non-list result; scan is incomplete.")
    return {str(item["path"]): item for item in rows if isinstance(item, dict) and "path" in item}


def _powershell_function_contracts(root: Path, contents: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    paths = [relative for relative in contents if Path(relative).suffix.casefold() == ".ps1"]
    if not paths:
        return {}
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return {
            relative: {"path": relative, "contracts": [], "parse_diagnostics": [],
                       "parser_status": "POWERSHELL_PARSER_UNAVAILABLE"}
            for relative in paths
        }
    helper = Path(__file__).with_name("dsh_powershell_contracts.ps1")
    try:
        completed = subprocess.run(
            [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-File", str(helper), "-Root", str(root)],
            input=json.dumps(paths), capture_output=True, text=True, check=False, timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"PowerShell AST extraction could not run ({type(exc).__name__}).") from exc
    if completed.returncode != 0:
        raise RuntimeError(
            f"PowerShell AST extraction failed closed (exit {completed.returncode}; "
            f"stderr sha256 {_sha(completed.stderr.encode('utf-8', errors='replace'))}; "
            f"diagnostic {completed.stderr[:500].strip()!r})."
        )
    try:
        rows = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("PowerShell AST extractor returned invalid JSON; scan is incomplete.") from exc
    if isinstance(rows, dict):
        rows = [rows]
    if not isinstance(rows, list):
        raise RuntimeError("PowerShell AST extractor returned a non-list result; scan is incomplete.")
    return {str(item["path"]): item for item in rows if isinstance(item, dict) and "path" in item}


def _shell_script_contracts(root: Path, contents: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    paths = [relative for relative in contents if Path(relative).suffix.casefold() == ".sh"]
    if not paths:
        return {}
    helper = Path(__file__).with_name("dsh_shell_parse.py")
    results: dict[str, dict[str, Any]] = {}
    for relative in paths:
        try:
            completed = subprocess.run(
                [sys.executable, str(helper), str(root)], input=json.dumps([relative]),
                capture_output=True, text=True, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            results[relative] = {
                "path": relative,
                "parser_status": f"SHELL_AST_HELPER_{type(exc).__name__.upper()}",
            }
            continue
        if completed.returncode != 0:
            results[relative] = {
                "path": relative,
                "parser_status": f"SHELL_AST_HELPER_EXIT_{completed.returncode}",
                "diagnostic_digest": _sha(completed.stderr.encode("utf-8", errors="replace")),
            }
            continue
        try:
            rows = json.loads(completed.stdout)
        except json.JSONDecodeError:
            results[relative] = {"path": relative, "parser_status": "SHELL_AST_INVALID_JSON"}
            continue
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            results[relative] = {"path": relative, "parser_status": "SHELL_AST_INVALID_RESULT"}
            continue
        results[relative] = rows[0]
    return results


def _script_invocation_units(contents: dict[str, bytes]) -> list[dict[str, Any]]:
    invocation_re = re.compile(
        r"(?<![A-Za-z0-9_./-])(?:(?P<shell>bash|sh|cmd|call|makensis)"
        r"(?:\s+(?:-[A-Za-z]+|/[A-Za-z]+))*\s+)?"
        r"(?P<target>(?:\./)?[A-Za-z0-9_./-]+\.(?:sh|cmd|bat|nsi))(?=\s|$)"
    )
    units: list[dict[str, Any]] = []

    def add_matches(path: str, field: str, value: str, base: Path, line_hint: int | None = None) -> None:
        for ordinal, match in enumerate(invocation_re.finditer(value)):
            target = (base / match.group("target")).as_posix()
            target = Path(target).as_posix()
            while target.startswith("./"):
                target = target[2:]
            target = os.path.normpath(target).replace("\\", "/")
            line = line_hint or value.count("\n", 0, match.start()) + 1
            command_digest = _sha(match.group(0).encode("utf-8", errors="replace"))
            contract = {
                "launcher": match.group("shell") or "direct",
                "field_path": field,
                "target_path": target,
                "target_exists": target in contents,
                "source_span": {"start_line": line, "end_line": line},
                "command_digest": command_digest,
            }
            units.append({
                "unit_id": _unit_id(path, "script_invocation_edge", f"{field}->{target}",
                                    json.dumps(contract, sort_keys=True), ordinal),
                "path": path,
                "symbol": f"{match.group('shell') or 'direct'}->{target}",
                "kind": "script_invocation_edge",
                "line": line,
                "digest": command_digest,
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": contract,
            })

    for relative, data in contents.items():
        suffix = Path(relative).suffix.casefold()
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if suffix == ".json":
            try:
                document = json.loads(text)
            except json.JSONDecodeError:
                continue
            if Path(relative).name == "package.json" and isinstance(document, dict):
                scripts = document.get("scripts")
                if isinstance(scripts, dict):
                    for name, command in sorted(scripts.items()):
                        if isinstance(command, str):
                            add_matches(relative, f"scripts.{name}", command, Path(relative).parent)
            elif isinstance(document, dict):
                stack: list[tuple[Any, tuple[str, ...]]] = [(document, ())]
                while stack:
                    value, parents = stack.pop()
                    if isinstance(value, dict):
                        stack.extend((child, (*parents, str(key))) for key, child in value.items())
                    elif isinstance(value, list):
                        stack.extend((child, parents) for child in value)
                    elif isinstance(value, str) and parents and parents[-1].casefold() in {"command", "run"}:
                        add_matches(relative, ".".join(parents), value, Path(relative).parent)
        elif suffix in {".yaml", ".yml"}:
            for line_number, line in enumerate(text.splitlines(), 1):
                match = re.match(r"^\s*(?:-\s*)?(run|command)\s*:\s*(.*?)\s*$", line)
                if match and match.group(2) and match.group(2) not in {"|", ">", "|-", ">-"}:
                    value = match.group(2).strip().strip("\"'")
                    add_matches(relative, f"{match.group(1)}@{line_number}", value, Path("."), line_number)
    macro_definitions: dict[str, list[str]] = {}
    macro_invocations: list[tuple[str, int, str]] = []
    include_re = re.compile(r"^\s*!include\s+(?:\"([^\"]+)\"|'([^']+)'|(\S+))", re.IGNORECASE)
    macro_re = re.compile(r"^\s*!macro\s+([A-Za-z_][A-Za-z0-9_.-]*)\b", re.IGNORECASE)
    insert_re = re.compile(r"^\s*!insertmacro\s+([A-Za-z_][A-Za-z0-9_.-]*)\b", re.IGNORECASE)
    for relative, data in contents.items():
        if Path(relative).suffix.casefold() not in {".nsi", ".nsh"}:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            definition = macro_re.match(line)
            if definition:
                macro_definitions.setdefault(definition.group(1).casefold(), []).append(relative)
            invocation = insert_re.match(line)
            if invocation:
                macro_invocations.append((relative, line_number, invocation.group(1)))
            include = include_re.match(line)
            if include:
                target_value = next((part for part in include.groups() if part is not None), "")
                dynamic = bool(re.search(r"\$\{|\$\(|%[^%]+%", target_value))
                target_path = None
                if target_value and not dynamic:
                    target_path = os.path.normpath(
                        (Path(relative).parent / target_value).as_posix()
                    ).replace("\\", "/")
                digest = _sha(line.encode("utf-8", errors="replace"))
                contract = {
                    "field_path": f"!include@{line_number}",
                    "target_path": target_path,
                    "target_exists": target_path in contents if target_path else False,
                    "dynamic_target_unresolved": dynamic or target_path is None,
                    "source_span": {"start_line": line_number, "end_line": line_number},
                    "command_digest": digest,
                }
                units.append({
                    "unit_id": _unit_id(relative, "nsis_include_edge", str(target_path or "<dynamic>"),
                                        json.dumps(contract, sort_keys=True), line_number),
                    "path": relative,
                    "symbol": f"!include@{line_number}",
                    "kind": "nsis_include_edge",
                    "line": line_number,
                    "digest": digest,
                    "resolution": "UNRESOLVED",
                    "atomic_ids": [],
                    "interaction_ids": [],
                    "contract": contract,
                })
    for relative, line_number, macro_name in macro_invocations:
        targets = sorted(macro_definitions.get(macro_name.casefold(), []))
        digest = _sha(macro_name.encode("utf-8", errors="replace"))
        contract = {
            "macro_name": macro_name,
            "target_paths": targets,
            "target_exists": bool(targets),
            "source_span": {"start_line": line_number, "end_line": line_number},
            "name_digest": digest,
        }
        units.append({
            "unit_id": _unit_id(relative, "nsis_macro_invocation_edge", macro_name,
                                json.dumps(contract, sort_keys=True), line_number),
            "path": relative,
            "symbol": f"!insertmacro:{macro_name}",
            "kind": "nsis_macro_invocation_edge",
            "line": line_number,
            "digest": digest,
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
            "contract": contract,
        })
    return units


def _windows_script_line_contracts(path: str, text: str) -> list[dict[str, Any]]:
    suffix = Path(path).suffix.casefold()
    units: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if not stripped:
            continue
        digest = _sha(line.encode("utf-8", errors="replace"))
        source_span = {"start_line": line_number, "end_line": line_number}
        contract: dict[str, Any] = {
            "source_span": source_span,
            "line_digest": digest,
            "parse_status": "LEXICAL_CONTRACT_UNRESOLVED",
        }
        if suffix == ".cmd":
            label = re.match(r"^:([^:\s]+)\s*$", stripped)
            command = re.match(r"^@?([A-Za-z_][A-Za-z0-9_]*)\b(.*)$", stripped)
            command_name = command.group(1).casefold() if command else ""
            arguments = command.group(2).strip() if command else ""
            dynamic = bool(re.search(r"%[^%]+%|%~[A-Za-z]|![A-Za-z_][A-Za-z0-9_]*!", arguments))
            if label:
                kind = "windows_batch_label"
                contract["label_name"] = label.group(1)
            elif command_name == "echo" and arguments.casefold() == "off":
                kind = "windows_batch_echo_mode"
            elif command_name in {"setlocal", "endlocal"}:
                kind = "windows_batch_scope"
                contract["scope_operation"] = command_name
                contract["argument_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
            elif command_name == "set":
                assignment = re.match(r"(?:/[^\s]+\s+)?\"?([A-Za-z_][A-Za-z0-9_]*)=(.*)\"?$", arguments)
                kind = "windows_batch_assignment" if assignment else "windows_batch_command"
                if assignment:
                    contract["variable_name"] = assignment.group(1)
                    contract["value_digest"] = _sha(assignment.group(2).encode("utf-8", errors="replace"))
                    contract["value_dynamic"] = bool(re.search(
                        r"%[^%]+%|%~[A-Za-z]|![A-Za-z_][A-Za-z0-9_]*!", assignment.group(2),
                    ))
            elif command_name == "if":
                kind = "windows_batch_control_flow"
                contract["condition_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
                contract["condition_dynamic"] = dynamic
            elif command_name == "for":
                kind = "windows_batch_loop"
                contract["loop_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
            elif command_name in {"goto", "call", "exit", "start", "pushd", "popd", "shift"}:
                kind = "windows_batch_dynamic_target" if command_name in {"goto", "call", "start"} and dynamic \
                    else "windows_batch_control_transfer" if command_name in {"goto", "call", "exit"} \
                    else "windows_batch_command"
                contract["command"] = command_name
                contract["argument_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
                contract["dynamic_target_unresolved"] = dynamic if command_name in {"goto", "call", "start"} else False
            elif command_name in {"rem"} or stripped.startswith("::"):
                kind = "windows_batch_comment_unresolved"
            else:
                kind = "windows_batch_command_unresolved"
                contract["command_digest"] = _sha((command_name or stripped.split()[0]).encode("utf-8", errors="replace"))
                contract["argument_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
                contract["dynamic_value_unresolved"] = dynamic
        else:
            token_match = re.match(r"^!?([A-Za-z][A-Za-z0-9_]*)\b(.*)$", stripped)
            token = token_match.group(1).casefold() if token_match else "<unclassified>"
            arguments = token_match.group(2).strip() if token_match else stripped
            dynamic = bool(re.search(r"\$\{|\$\(|%[^%]+%", arguments))
            contract["token"] = token
            contract["argument_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
            contract["dynamic_value_unresolved"] = dynamic
            if token == "include":
                kind = "nsis_include"
                contract["target_digest"] = _sha(arguments.encode("utf-8", errors="replace"))
                contract["dynamic_target_unresolved"] = dynamic
            elif token in {"ifdef", "ifndef", "if", "elseif", "else", "endif"}:
                kind = "nsis_conditional"
            elif token in {"function", "functionend"}:
                kind = "nsis_function"
            elif token in {"macro", "macroend"}:
                kind = "nsis_macro"
            elif token == "insertmacro":
                kind = "nsis_macro_invocation"
                macro_name = arguments.split(maxsplit=1)[0].strip("\"'") if arguments else ""
                contract["macro_name"] = macro_name
                contract["macro_name_digest"] = _sha(macro_name.encode("utf-8", errors="replace"))
            elif token in {"section", "sectionend", "sectiongroup", "sectiongroupend"}:
                kind = "nsis_section"
            elif token in {"define", "var"}:
                kind = "nsis_default_or_variable"
            elif token in {
                "strcpy", "intop", "writeinistr", "writeregstr", "writeregdword",
                "deleteregkey", "deleteregvalue", "setoutpath", "file", "delete", "rmdir",
                "exec", "execwait", "call", "return", "quit", "abort", "seterrorlevel",
                "iferrors", "clearerrors", "push", "pop", "createdirectory",
            }:
                kind = "nsis_install_state"
            else:
                kind = "nsis_line_unresolved"
        symbol = f"{kind.upper()}_{line_number}"
        units.append({
            "unit_id": _unit_id(path, kind, symbol, digest, line_number),
            "path": path,
            "symbol": symbol,
            "kind": kind,
            "line": line_number,
            "digest": digest,
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
            "contract": contract,
        })
    return units


def _semantic_units(
    path: str, text: str, typescript_row: dict[str, Any] | None = None,
    powershell_row: dict[str, Any] | None = None,
    shell_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    seen: Counter[tuple[str, str]] = Counter()
    suffix = Path(path).suffix.casefold()
    classified = _classify(path)
    if suffix == ".css":
        units.extend(_css_style_units(path, text))
        units.append({
            "unit_id": _unit_id(path, "file_review", "<file-review>", path, 0),
            "path": path,
            "symbol": "<file-review>",
            "kind": "file_review",
            "line": 1,
            "digest": _sha(text.encode("utf-8", errors="replace")),
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
        })
        return units
    exceptions_by_line: dict[int, list[str]] = {}
    python_contracts: dict[int, dict[str, Any]] = {}
    if suffix == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            tree = None
        if tree is not None:
            python_contracts = _python_function_contracts(text, tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.ExceptHandler):
                    continue
                if node.type is None:
                    names = ["<bare-except>"]
                elif isinstance(node.type, ast.Tuple):
                    names = [ast.unparse(item) for item in node.type.elts]
                else:
                    names = [ast.unparse(node.type)]
                exceptions_by_line.setdefault(node.lineno, []).extend(names)
    for line_number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        candidates: list[tuple[str, str]] = []
        candidates.extend(
            ("exception_branch", name)
            for name in exceptions_by_line.get(line_number, [])
        )
        if suffix == ".py":
            match = PY_DECL_RE.match(line)
            if match:
                candidates.append(("declaration", match.group(1)))
        else:
            match = EXPORT_RE.match(line)
            if match:
                candidates.append(("export", match.group(1)))
            elif suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts", ".vue"}:
                match = JS_FUNC_RE.match(line)
                if match:
                    candidates.append(("method_candidate", match.group(1)))
                else:
                    match = TS_DECL_RE.match(line)
                    if match and not stripped.startswith(("if ", "if(", "for ", "for(", "while ", "switch ", "catch ")):
                        candidates.append(("method_candidate", match.group(1)))
        if PLATFORM_RE.search(line):
            candidates.append(("platform_branch", f"line:{line_number}"))
        if STATE_RE.search(line):
            candidates.append(("state_transition", f"line:{line_number}"))
        if PROTOCOL_RE.search(line):
            candidates.append(("protocol_or_registration", f"line:{line_number}"))
        if DEFAULT_RE.search(line):
            candidates.append(("configuration_default", f"line:{line_number}"))
        if IMPORT_RE.match(line):
            candidates.append(("consumer_import", f"line:{line_number}"))
        for kind, symbol in candidates:
            key = (kind, symbol)
            ordinal = seen[key]
            seen[key] += 1
            unit = {
                "unit_id": _unit_id(path, kind, symbol, line, ordinal),
                "path": path,
                "symbol": symbol,
                "kind": kind,
                "line": line_number,
                "digest": _sha(line.encode("utf-8", errors="replace")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
            }
            if suffix == ".py" and kind == "declaration" and line_number in python_contracts:
                unit["contract"] = python_contracts[line_number]
            units.append(unit)
    units.extend(_configuration_field_units(path, text))
    if typescript_row is not None:
        if typescript_row.get("parser_status"):
            status = str(typescript_row["parser_status"])
            units.append({
                "unit_id": _unit_id(path, "typescript_parser_unavailable", status, status, 0),
                "path": path,
                "symbol": status,
                "kind": "typescript_parser_unavailable",
                "line": 0,
                "digest": _sha(status.encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", "reason_code": status},
            })
        for ordinal, contract in enumerate(typescript_row.get("contracts", [])):
            start_line = int(contract.get("source_span", {}).get("start_line") or 0)
            end_line = int(contract.get("source_span", {}).get("end_line") or start_line)
            source_fragment = "\n".join(text.splitlines()[max(0, start_line - 1):end_line])
            units.append({
                "unit_id": _unit_id(path, "typescript_function_contract", str(contract.get("qualname") or ""),
                                    json.dumps(contract, sort_keys=True), ordinal),
                "path": path,
                "symbol": str(contract.get("qualname") or "<anonymous>"),
                "kind": "typescript_function_contract",
                "line": start_line,
                "digest": _sha(source_fragment.encode("utf-8", errors="replace")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": contract,
            })
        for ordinal, diagnostic in enumerate(typescript_row.get("parse_diagnostics", [])):
            line_number = int(diagnostic.get("line") or 0)
            symbol = f"TS_PARSE_{diagnostic.get('code', 'UNKNOWN')}"
            units.append({
                "unit_id": _unit_id(path, "typescript_parse_error", symbol, json.dumps(diagnostic, sort_keys=True), ordinal),
                "path": path,
                "symbol": symbol,
                "kind": "typescript_parse_error",
                "line": line_number,
                "digest": _sha(json.dumps(diagnostic, sort_keys=True).encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", **diagnostic},
            })
    if powershell_row is not None:
        parser_status = powershell_row.get("parser_status")
        if parser_status:
            units.append({
                "unit_id": _unit_id(path, "powershell_parser_unavailable", str(parser_status), str(parser_status), 0),
                "path": path,
                "symbol": str(parser_status),
                "kind": "powershell_parser_unavailable",
                "line": 0,
                "digest": _sha(str(parser_status).encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", "reason_code": str(parser_status)},
            })
        for ordinal, contract in enumerate(powershell_row.get("contracts", [])):
            start_line = int(contract.get("source_span", {}).get("start_line") or 0)
            end_line = int(contract.get("source_span", {}).get("end_line") or start_line)
            source_fragment = "\n".join(text.splitlines()[max(0, start_line - 1):end_line])
            units.append({
                "unit_id": _unit_id(path, "powershell_function_contract", str(contract.get("qualname") or ""),
                                    json.dumps(contract, sort_keys=True), ordinal),
                "path": path,
                "symbol": str(contract.get("qualname") or "<anonymous>"),
                "kind": "powershell_function_contract",
                "line": start_line,
                "digest": _sha(source_fragment.encode("utf-8", errors="replace")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": contract,
            })
        for ordinal, diagnostic in enumerate(powershell_row.get("parse_diagnostics", [])):
            line_number = int(diagnostic.get("line") or 0)
            symbol = f"POWERSHELL_PARSE_{diagnostic.get('error_id', 'UNKNOWN')}"
            units.append({
                "unit_id": _unit_id(path, "powershell_parse_error", symbol,
                                    json.dumps(diagnostic, sort_keys=True), ordinal),
                "path": path,
                "symbol": symbol,
                "kind": "powershell_parse_error",
                "line": line_number,
                "digest": _sha(json.dumps(diagnostic, sort_keys=True).encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", **diagnostic},
            })
    if shell_row is not None:
        parser_status = shell_row.get("parser_status")
        if parser_status:
            units.append({
                "unit_id": _unit_id(path, "shell_parser_unavailable", str(parser_status), str(parser_status), 0),
                "path": path,
                "symbol": str(parser_status),
                "kind": "shell_parser_unavailable",
                "line": 0,
                "digest": _sha(str(parser_status).encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", "reason_code": str(parser_status)},
            })
            if suffix == ".sh":
                for line_number, source_line in enumerate(text.splitlines(), start=1):
                    if not source_line.strip():
                        continue
                    line_digest = _sha(source_line.encode("utf-8", errors="replace"))
                    symbol = f"OPAQUE_SHELL_LINE_{line_number}"
                    units.append({
                        "unit_id": _unit_id(path, "shell_opaque_line_unresolved", symbol,
                                            line_digest, line_number),
                        "path": path,
                        "symbol": symbol,
                        "kind": "shell_opaque_line_unresolved",
                        "line": line_number,
                        "digest": line_digest,
                        "resolution": "UNRESOLVED",
                        "atomic_ids": [],
                        "interaction_ids": [],
                        "contract": {
                            "parse_status": "UNRESOLVED",
                            "reason_code": str(parser_status),
                            "source_span": {"start_line": line_number, "end_line": line_number},
                            "line_digest": line_digest,
                        },
                    })
        for ordinal, contract in enumerate(shell_row.get("contracts", [])):
            start_line = int(contract.get("source_span", {}).get("start_line") or 0)
            end_line = int(contract.get("source_span", {}).get("end_line") or start_line)
            source_fragment = "\n".join(text.splitlines()[max(0, start_line - 1):end_line])
            kind_map = {
                "shell_syntax_only": "shell_syntax_contract",
                "bash_function": "shell_function_contract",
                "bash_control_flow": "shell_control_flow_contract",
                "bash_command": "shell_command_contract",
                "bash_dynamic_command_unresolved": "shell_dynamic_command_unresolved",
                "bash_shell_options": "shell_error_policy_contract",
                "bash_trap": "shell_trap_contract",
                "bash_status_transition": "shell_status_transition_contract",
                "bash_platform_condition": "shell_platform_condition_contract",
                "bash_launch_target": "shell_launch_target_contract",
                "bash_dynamic_launch_unresolved": "shell_dynamic_launch_unresolved",
            }
            unit_kind = kind_map.get(str(contract.get("kind")), "shell_contract_unclassified")
            symbol = str(contract.get("name") or contract.get("node_type") or contract.get("transition")
                         or contract.get("invocation") or contract.get("kind") or "<shell-syntax>")
            units.append({
                "unit_id": _unit_id(path, unit_kind, symbol,
                                    json.dumps(contract, sort_keys=True), ordinal),
                "path": path,
                "symbol": symbol,
                "kind": unit_kind,
                "line": start_line,
                "digest": _sha(source_fragment.encode("utf-8", errors="replace")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parser": shell_row.get("parser"), **contract},
            })
        for ordinal, diagnostic in enumerate(shell_row.get("parse_diagnostics", [])):
            line_number = int(diagnostic.get("line") or 0)
            symbol = f"SHELL_PARSE_LINE_{line_number}"
            units.append({
                "unit_id": _unit_id(path, "shell_parse_error", symbol,
                                    json.dumps(diagnostic, sort_keys=True), ordinal),
                "path": path,
                "symbol": symbol,
                "kind": "shell_parse_error",
                "line": line_number,
                "digest": _sha(json.dumps(diagnostic, sort_keys=True).encode("utf-8")),
                "resolution": "UNRESOLVED",
                "atomic_ids": [],
                "interaction_ids": [],
                "contract": {"parse_status": "UNRESOLVED", **diagnostic},
            })
    elif Path(path).suffix.casefold() in {".cmd", ".nsi", ".nsh"}:
        language = Path(path).suffix.casefold().lstrip(".").upper()
        units.append({
            "unit_id": _unit_id(path, "script_parser_unavailable", language, language, 0),
            "path": path,
            "symbol": f"<{language}-parser-unavailable>",
            "kind": "script_parser_unavailable",
            "line": 0,
            "digest": _sha(language.encode("utf-8")),
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
            "contract": {"parse_status": "UNRESOLVED", "language": language},
        })
        units.extend(_windows_script_line_contracts(path, text))
    if classified == "source":
        units.append({
            "unit_id": _unit_id(path, "file_review", "<file-review>", path, 0),
            "path": path,
            "symbol": "<file-review>",
            "kind": "file_review",
            "line": 1,
            "digest": _sha(text.encode("utf-8", errors="replace")),
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
        })
    return units


def _css_style_units(path: str, text: str) -> list[dict[str, Any]]:
    """Index CSS selectors and at-rules without evaluating styles or imports."""
    units: list[dict[str, Any]] = []
    ordinal_by_symbol: Counter[tuple[str, str]] = Counter()

    def next_boundary(start: int, end: int) -> tuple[int, str | None]:
        index = start
        quote: str | None = None
        parens = brackets = 0
        while index < end:
            char = text[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if text.startswith("/*", index):
                close = text.find("*/", index + 2, end)
                if close < 0:
                    return end, None
                index = close + 2
                continue
            if char == "(":
                parens += 1
            elif char == ")" and parens:
                parens -= 1
            elif char == "[":
                brackets += 1
            elif char == "]" and brackets:
                brackets -= 1
            elif not parens and not brackets and char in "{};":
                return index, char
            index += 1
        return end, None

    def matching_close(opening: int, end: int) -> int | None:
        depth = 1
        index = opening + 1
        quote: str | None = None
        while index < end:
            char = text[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if text.startswith("/*", index):
                close = text.find("*/", index + 2, end)
                if close < 0:
                    return None
                index = close + 2
                continue
            if char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
            index += 1
        return None

    def clean_prelude(raw: str) -> str:
        output: list[str] = []
        index = 0
        quote: str | None = None
        while index < len(raw):
            char = raw[index]
            if quote:
                output.append(char)
                if char == "\\" and index + 1 < len(raw):
                    output.append(raw[index + 1])
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                output.append(char)
                index += 1
                continue
            if raw.startswith("/*", index):
                close = raw.find("*/", index + 2)
                if close < 0:
                    break
                output.append(" ")
                index = close + 2
                continue
            output.append(char)
            index += 1
        return "".join(output).strip()

    def declarations(start: int, end: int) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        segment_start = start
        index = start
        quote: str | None = None
        parens = brackets = 0
        while index <= end:
            char = text[index] if index < end else ";"
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = None
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                index += 1
                continue
            if text.startswith("/*", index):
                close = text.find("*/", index + 2, end)
                if close < 0:
                    break
                index = close + 2
                continue
            if char == "(":
                parens += 1
            elif char == ")" and parens:
                parens -= 1
            elif char == "[":
                brackets += 1
            elif char == "]" and brackets:
                brackets -= 1
            elif char == "{" and not parens and not brackets:
                close = matching_close(index, end)
                if close is None:
                    break
                segment_start = close + 1
                index = close + 1
                continue
            elif char == ";" and not parens and not brackets:
                segment = text[segment_start:index].strip()
                if ":" in segment and not segment.startswith("@"):
                    prop, value = segment.split(":", 1)
                    prop = prop.strip()
                    value = value.strip()
                    if re.fullmatch(r"(?:--[\w-]+|-?[A-Za-z_][\w-]*)", prop) and value:
                        result.append({"property": prop, "value_sha256": _sha(value.encode("utf-8"))})
                segment_start = index + 1
            index += 1
        return result

    def emit(kind: str, prelude: str, start: int, end: int, parents: list[str],
             direct_declarations: list[dict[str, str]]) -> None:
        symbol = prelude or "<empty-css-prelude>"
        ordinal_key = (kind, symbol)
        ordinal = ordinal_by_symbol[ordinal_key]
        ordinal_by_symbol[ordinal_key] += 1
        fragment = text[start:end]
        start_line = text.count("\n", 0, start) + 1
        end_line = text.count("\n", 0, end) + 1
        units.append({
            "unit_id": _unit_id(path, kind, symbol, fragment, ordinal),
            "path": path,
            "symbol": symbol,
            "kind": kind,
            "line": start_line,
            "digest": _sha(fragment.encode("utf-8", errors="replace")),
            "resolution": "UNRESOLVED",
            "atomic_ids": [],
            "interaction_ids": [],
            "contract": {
                "rule_type": "directive" if kind == "css_directive" else (
                    "at_rule" if prelude.startswith("@") else "selector"
                ),
                "prelude": prelude,
                "parents": list(parents),
                "declarations": direct_declarations,
                "source_span": {"start_line": start_line, "end_line": end_line},
            },
        })

    def parse_range(start: int, end: int, parents: list[str]) -> None:
        cursor = start
        while cursor < end:
            boundary, delimiter = next_boundary(cursor, end)
            prelude = clean_prelude(text[cursor:boundary])
            if delimiter == ";":
                if prelude.startswith("@"):
                    emit("css_directive", prelude, cursor, boundary + 1, parents, [])
                cursor = boundary + 1
                continue
            if delimiter == "{":
                close = matching_close(boundary, end)
                if close is None:
                    emit("css_parse_unresolved", prelude or "<unclosed-block>", cursor, end, parents, [])
                    return
                if prelude:
                    kind = "css_rule"
                    emit(kind, prelude, cursor, close + 1, parents,
                         declarations(boundary + 1, close))
                    parse_range(boundary + 1, close, [*parents, prelude])
                cursor = close + 1
                continue
            if delimiter == "}":
                return
            if prelude:
                emit("css_parse_unresolved", prelude, cursor, end, parents, [])
            return

    parse_range(0, len(text), [])
    return units


def build_source_index(
    source: str | Path, *, typescript_module: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(source).resolve()
    if not root.is_dir():
        raise ValueError(f"source root is not a directory: {root}")
    head, paths = _git_paths(root)
    if not paths:
        paths = _filesystem_paths(root)
    files: list[dict[str, Any]] = []
    manifests: list[dict[str, Any]] = []
    package_roots: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for relative in paths:
        path = root / Path(relative)
        try:
            data = path.read_bytes()
        except OSError as exc:
            files.append({"path": relative, "digest": None, "classification": "unreadable",
                          "component_id": None, "error_type": type(exc).__name__})
            continue
        contents[relative] = data
        digest = _sha(data)
        classification = _classify(relative)
        files.append({
            "path": relative,
            "digest": digest,
            "classification": classification,
            "component_id": None,
            "discovery_parent": "repository-root",
        })
        if Path(relative).name == "package.json":
            try:
                manifest = json.loads(data.decode("utf-8"))
                name = str(manifest.get("name") or Path(relative).parent.as_posix() or "root")
                package_root = Path(relative).parent.as_posix()
                package_roots[package_root] = name
                manifests.append({"path": relative, "digest": digest, "manifest": manifest})
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                manifests.append({"path": relative, "digest": digest, "parse_status": "UNRESOLVED"})
    for record in files:
        record["component_id"] = _component_for(record["path"], package_roots)
        record["scope_id"] = _scope_for(record["path"], record["component_id"])
    typescript_contracts = _typescript_function_contracts(root, contents, typescript_module)
    powershell_contracts = _powershell_function_contracts(root, contents)
    shell_contracts = _shell_script_contracts(root, contents)
    components = []
    for item in manifests:
        manifest = item.get("manifest")
        if not isinstance(manifest, dict):
            continue
        rel = item["path"]
        components.append({
            "component_id": str(manifest.get("name") or Path(rel).parent.as_posix() or "root"),
            "root": Path(rel).parent.as_posix(),
            "manifest_path": rel,
            "manifest_digest": item["digest"],
            "exports": manifest.get("exports", {}),
            "main": manifest.get("main"),
            "scripts": manifest.get("scripts", {}),
            "dependencies": manifest.get("dependencies", {}),
            "peerDependencies": manifest.get("peerDependencies", {}),
            "optionalDependencies": manifest.get("optionalDependencies", {}),
        })
    semantic: list[dict[str, Any]] = []
    entry_points: list[dict[str, Any]] = []
    for relative, data in contents.items():
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
            if _classify(relative) == "source":
                semantic.append({
                    "unit_id": _unit_id(relative, "binary_source", "<binary>", _sha(data), 0),
                    "path": relative, "symbol": "<binary>", "kind": "binary_source",
                    "line": 0, "digest": _sha(data), "resolution": "UNRESOLVED", "atomic_ids": [],
                })
        semantic.extend(_semantic_units(
            relative, text, typescript_contracts.get(relative), powershell_contracts.get(relative),
            shell_contracts.get(relative),
        ))
        if Path(relative).name == "package.json":
            try:
                manifest = json.loads(text)
            except json.JSONDecodeError:
                manifest = {}
            if isinstance(manifest, dict):
                for key in ("exports", "main", "module", "types", "bin", "scripts"):
                    if key in manifest:
                        entry_points.append({"entry_id": _unit_id(relative, "package_entry", key,
                                                                    json.dumps(manifest[key], sort_keys=True), 0),
                                             "path": relative, "kind": "package_" + key,
                                             "value": manifest[key], "component_id": manifest.get("name"),
                                             "digest": next(
                                                 item["digest"] for item in files if item["path"] == relative
                                             ),
                                             "resolution": "UNRESOLVED", "atomic_ids": [],
                                             "interaction_ids": []})
    semantic.extend(_script_invocation_units(contents))
    scope_by_path = {record["path"]: record["scope_id"] for record in files}
    scope_counts: dict[str, dict[str, Any]] = {}
    for record in files:
        scope = scope_counts.setdefault(record["scope_id"], {
            "scope_id": record["scope_id"], "file_count": 0, "semantic_unit_count": 0,
            "classifications": {},
        })
        scope["file_count"] += 1
        classification = str(record.get("classification") or "unknown")
        scope["classifications"][classification] = scope["classifications"].get(classification, 0) + 1
    for unit in semantic:
        unit["scope_id"] = scope_by_path.get(unit["path"], _scope_for(unit["path"], None))
        scope = scope_counts.setdefault(unit["scope_id"], {
            "scope_id": unit["scope_id"], "file_count": 0, "semantic_unit_count": 0,
            "classifications": {},
        })
        scope["semantic_unit_count"] += 1
    configuration_fields = {
        (unit["path"], unit["contract"]["field_path"]): unit
        for unit in semantic
        if unit.get("kind") == "configuration_field"
        and isinstance(unit.get("contract"), dict)
        and unit["contract"].get("field_path")
    }
    for unit in semantic:
        if unit.get("kind") != "typescript_function_contract":
            continue
        contract = unit.get("contract", {})
        consumers_by_field: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for read in contract.get("configuration_reads", []):
            if read.get("resolution") != "resolved_json_field":
                continue
            target = configuration_fields.get((read.get("config_path"), read.get("field_path")))
            if target is None:
                read["resolution"] = "unresolved_config_field_unit"
                continue
            read["configuration_field_unit_id"] = target["unit_id"]
            key = (str(read["config_path"]), str(read["field_path"]))
            consumers_by_field.setdefault(key, []).append({
                "path": unit["path"],
                "qualname": contract.get("qualname"),
                "line": read.get("line"),
                "access": read.get("field_path"),
            })
        for key, consumers in consumers_by_field.items():
            target = configuration_fields[key]
            existing = target.setdefault("consumers", [])
            for consumer in consumers:
                if consumer not in existing:
                    existing.append(consumer)
    return {
        "schema_version": 3,
        "extractor_version": EXTRACTOR_VERSION,
        "source": {
            "root_name": root.name,
            "head": head,
            "expected_head": PINNED_DSH_COMMIT,
            "pinned_head_match": head == PINNED_DSH_COMMIT if head else None,
        },
        "files": files,
        "components": sorted(components, key=lambda row: row["component_id"]),
        "scopes": sorted(scope_counts.values(), key=lambda row: row["scope_id"]),
        "entry_points": entry_points,
        "semantic_coverage": semantic,
        "summary": {
            "file_count": len(files),
            "package_manifest_count": len(manifests),
            "component_count": len(components),
            "semantic_unit_count": len(semantic),
            "unresolved_semantic_unit_count": len(semantic),
        },
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            rows.append({"__parse_error__": f"line {line_number}: {exc.msg}"})
            continue
        rows.append(item if isinstance(item, dict) else {"__parse_error__": f"line {line_number}: not object"})
    return rows


def check_source_index(
    source: str | Path,
    baseline: dict[str, Any],
    *,
    atomic_rows: list[dict[str, Any]] | None = None,
    interaction_rows: list[dict[str, Any]] | None = None,
    typescript_module: str | Path | None = None,
) -> list[dict[str, Any]]:
    current = build_source_index(source, typescript_module=typescript_module)
    findings: list[dict[str, Any]] = []
    if baseline.get("extractor_version") != current.get("extractor_version"):
        findings.append({
            "code": "EXTRACTOR_VERSION_MISMATCH",
            "indexed": baseline.get("extractor_version"),
            "current": current.get("extractor_version"),
        })
    if baseline.get("schema_version") != current.get("schema_version"):
        findings.append({
            "code": "INDEX_SCHEMA_VERSION_MISMATCH",
            "indexed": baseline.get("schema_version"),
            "current": current.get("schema_version"),
        })
    old_files = {row["path"]: row for row in baseline.get("files", []) if isinstance(row, dict)}
    new_files = {row["path"]: row for row in current["files"]}
    for path in sorted(new_files.keys() - old_files.keys()):
        findings.append({"code": "SOURCE_FILE_ADDED", "path": path})
    for path in sorted(old_files.keys() - new_files.keys()):
        findings.append({"code": "SOURCE_FILE_REMOVED", "path": path})
    for path in sorted(old_files.keys() & new_files.keys()):
        if old_files[path].get("digest") != new_files[path].get("digest"):
            findings.append({"code": "SOURCE_DIGEST_CHANGED", "path": path})
    old_units = {row["unit_id"]: row for row in baseline.get("semantic_coverage", []) if isinstance(row, dict)}
    new_units = {row["unit_id"]: row for row in current["semantic_coverage"]}
    for unit_id in sorted(new_units.keys() - old_units.keys()):
        findings.append({"code": "SEMANTIC_UNIT_ADDED", "unit_id": unit_id, "path": new_units[unit_id]["path"]})
    for unit_id in sorted(old_units.keys() - new_units.keys()):
        findings.append({"code": "SEMANTIC_UNIT_REMOVED", "unit_id": unit_id, "path": old_units[unit_id]["path"]})
    atomics = atomic_rows or []
    interactions = interaction_rows or []
    atomic_ids = {row.get("atomic_id") for row in atomics if isinstance(row, dict)}
    interaction_ids = {
        identifier
        for row in interactions if isinstance(row, dict)
        if (identifier := row.get("interaction_id") or row.get("edge_id"))
    }
    for unit in baseline.get("semantic_coverage", []):
        if not isinstance(unit, dict):
            findings.append({"code": "SEMANTIC_UNIT_INVALID"})
            continue
        resolution = unit.get("resolution")
        links = unit.get("atomic_ids") or []
        interaction_links = unit.get("interaction_ids") or []
        if resolution == "UNRESOLVED":
            findings.append({"code": "SEMANTIC_UNIT_UNRESOLVED", "unit_id": unit.get("unit_id")})
        elif resolution == "MAPPED" and not (links or interaction_links):
            findings.append({"code": "SEMANTIC_MAPPING_EMPTY", "unit_id": unit.get("unit_id")})
        elif resolution == "EXCLUDED" and not (unit.get("exclusion_reason") and unit.get("evidence")):
            findings.append({"code": "EXCLUSION_UNEVIDENCED", "unit_id": unit.get("unit_id")})
        for atomic_id in links:
            if atomic_id not in atomic_ids:
                findings.append({"code": "REFERENCE_MISSING", "unit_id": unit.get("unit_id"),
                                 "reference": atomic_id})
        for interaction_id in interaction_links:
            if interaction_id not in interaction_ids:
                findings.append({"code": "REFERENCE_MISSING", "unit_id": unit.get("unit_id"),
                                 "reference": interaction_id})
    for entry in baseline.get("entry_points", []):
        if not isinstance(entry, dict):
            findings.append({"code": "ENTRY_POINT_INVALID"})
            continue
        entry_id = entry.get("entry_id")
        resolution = entry.get("resolution")
        atomic_links = entry.get("atomic_ids") or []
        interaction_links = entry.get("interaction_ids") or []
        if resolution == "UNRESOLVED" or resolution is None:
            findings.append({"code": "ENTRY_POINT_UNRESOLVED", "entry_id": entry_id})
        elif resolution == "MAPPED" and not (atomic_links or interaction_links):
            findings.append({"code": "ENTRY_POINT_MAPPING_EMPTY", "entry_id": entry_id})
        elif resolution == "EXCLUDED" and not (entry.get("exclusion_reason") and entry.get("evidence")):
            findings.append({"code": "ENTRY_POINT_EXCLUSION_UNEVIDENCED", "entry_id": entry_id})
        for reference in atomic_links:
            if reference not in atomic_ids:
                findings.append({"code": "REFERENCE_MISSING", "entry_id": entry_id,
                                 "reference": reference})
        for reference in interaction_links:
            if reference not in interaction_ids:
                findings.append({"code": "REFERENCE_MISSING", "entry_id": entry_id,
                                 "reference": reference})
    for row in atomics:
        if not isinstance(row, dict):
            findings.append({"code": "ATOMIC_ROW_INVALID"})
            continue
        if row.get("__parse_error__"):
            findings.append({"code": "LEDGER_PARSE_ERROR", "detail": row["__parse_error__"]})
        if row.get("implementation_status") == "CLOSED":
            evidence = row.get("evidence")
            if not isinstance(evidence, list) or not evidence or any(
                not isinstance(item, dict) or item.get("status") in {
                    "UNKNOWN", "BLOCKED", "UNVERIFIED", "FAKE_ONLY", "FAILED",
                } for item in evidence
            ):
                findings.append({"code": "FALSE_CLOSED", "atomic_id": row.get("atomic_id")})
            for unit_id in row.get("source_units", []):
                if unit_id not in old_units:
                    findings.append({"code": "REFERENCE_MISSING", "atomic_id": row.get("atomic_id"),
                                     "reference": unit_id})
    for row in interactions:
        if row.get("__parse_error__"):
            findings.append({"code": "LEDGER_PARSE_ERROR", "detail": row["__parse_error__"]})
        for key in ("provider_atomic_id", "consumer_atomic_id"):
            value = row.get(key)
            if value and value not in atomic_ids:
                findings.append({"code": "REFERENCE_MISSING", "interaction_id": row.get("interaction_id"),
                                 "reference": value})
    expected_head = baseline.get("source", {}).get("expected_head")
    current_head = current.get("source", {}).get("head")
    if expected_head and current_head and current_head != expected_head:
        findings.append({"code": "SOURCE_HEAD_MISMATCH", "expected": expected_head, "actual": current_head})
    return findings


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _apply_semantic_decisions(index: dict[str, Any], ledger: Path) -> None:
    decisions_path = ledger / "semantic-decisions.jsonl"
    decisions = _read_jsonl(decisions_path)
    if not decisions:
        return
    units = {item.get("unit_id"): item for item in index.get("semantic_coverage", [])}
    entries = {item.get("entry_id"): item for item in index.get("entry_points", [])}
    atomic_ids = {
        item.get("atomic_id") for item in _read_jsonl(ledger / "atomic-capabilities.jsonl")
        if isinstance(item, dict)
    }
    interaction_ids = {
        item.get("interaction_id") or item.get("edge_id")
        for item in _read_jsonl(ledger / "interaction-edges.jsonl")
        if isinstance(item, dict)
    }
    seen: set[str] = set()
    for row in decisions:
        if row.get("__parse_error__"):
            raise ValueError("invalid semantic decision JSONL")
        allowed_fields = {
            "schema_version", "source_head", "unit_id", "entry_id", "digest", "resolution",
            "atomic_ids", "interaction_ids", "evidence", "exclusion_reason",
        }
        if set(row) - allowed_fields:
            raise ValueError("semantic decision contains unsupported fields")
        unit_id = row.get("unit_id")
        entry_id = row.get("entry_id")
        has_unit_id = "unit_id" in row
        has_entry_id = "entry_id" in row
        if has_unit_id == has_entry_id:
            raise ValueError("semantic decision requires exactly one unit_id or entry_id")
        target_id = unit_id if has_unit_id else entry_id
        if not isinstance(target_id, str) or not target_id:
            raise ValueError("semantic decision target id must be a non-empty string")
        target_kind, target_id, targets = (
            ("entry", target_id, entries) if has_entry_id else ("unit", target_id, units)
        )
        decision_key = f"{target_kind}:{target_id}"
        if decision_key in seen:
            raise ValueError("semantic decisions require unique unit or entry ids")
        seen.add(decision_key)
        unit = targets.get(target_id)
        if unit is None:
            raise ValueError(f"semantic decision references unknown {target_kind}: {target_id}")
        if row.get("source_head") != index.get("source", {}).get("head"):
            raise ValueError(f"semantic decision source head mismatch: {target_id}")
        if row.get("digest") != unit.get("digest"):
            raise ValueError(f"stale semantic decision for {target_kind}: {target_id}")
        if type(row.get("schema_version")) is not int or row.get("schema_version") != 1:
            raise ValueError(f"unsupported semantic decision schema: {target_id}")
        resolution = row.get("resolution")
        if not isinstance(resolution, str) or resolution not in {"MAPPED", "EXCLUDED"}:
            raise ValueError(f"semantic decision has invalid resolution: {target_id}")
        atomic_refs = row.get("atomic_ids")
        interaction_refs = row.get("interaction_ids")
        evidence = row.get("evidence")
        if (not isinstance(atomic_refs, list) or not all(isinstance(value, str) for value in atomic_refs)
                or len(atomic_refs) != len(set(atomic_refs))):
            raise ValueError(f"semantic decision has invalid atomic references: {target_id}")
        if (not isinstance(interaction_refs, list)
                or not all(isinstance(value, str) for value in interaction_refs)
                or len(interaction_refs) != len(set(interaction_refs))):
            raise ValueError(f"semantic decision has invalid interaction references: {target_id}")
        if (not isinstance(evidence, list) or not evidence
                or not all(isinstance(value, str) and value.strip() for value in evidence)):
            raise ValueError(f"semantic decision requires evidence: {target_id}")
        if resolution == "MAPPED":
            if not (atomic_refs or interaction_refs):
                raise ValueError(f"mapped semantic decision requires a ledger reference: {target_id}")
            if any(value not in atomic_ids for value in atomic_refs):
                raise ValueError(f"semantic decision references missing atomic row: {target_id}")
            if any(value not in interaction_ids for value in interaction_refs):
                raise ValueError(f"semantic decision references missing interaction row: {target_id}")
        else:
            reason = row.get("exclusion_reason")
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(f"excluded semantic decision requires a reason: {target_id}")
            unit["exclusion_reason"] = reason
        unit["resolution"] = resolution
        unit["atomic_ids"] = atomic_refs
        unit["interaction_ids"] = interaction_refs
        unit["evidence"] = evidence


def scan_to_ledger(
    source: Path, ledger: Path, *, typescript_module: str | Path | None = None,
) -> dict[str, Any]:
    index = build_source_index(source, typescript_module=typescript_module)
    existing: dict[str, Any] = {}
    index_path = ledger / "source-index.json"
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
    old_files = {item.get("path"): item.get("digest") for item in existing.get("files", [])}
    old_units = {item.get("unit_id"): item for item in existing.get("semantic_coverage", [])}
    for unit in index["semantic_coverage"]:
        old = old_units.get(unit["unit_id"])
        if old and old_files.get(unit["path"]) == next(
            (item["digest"] for item in index["files"] if item["path"] == unit["path"]), None,
        ):
            for key in ("resolution", "atomic_ids", "interaction_ids", "exclusion_reason", "evidence"):
                if key in old:
                    unit[key] = old[key]
    old_entries = {item.get("entry_id"): item for item in existing.get("entry_points", [])}
    for entry in index["entry_points"]:
        old = old_entries.get(entry["entry_id"])
        if old and old.get("digest") == entry.get("digest"):
            for key in ("resolution", "atomic_ids", "interaction_ids", "exclusion_reason", "evidence"):
                if key in old:
                    entry[key] = old[key]
    _apply_semantic_decisions(index, ledger)
    index["summary"]["unresolved_semantic_unit_count"] = sum(
        1 for item in index["semantic_coverage"]
        if item.get("resolution") not in {"MAPPED", "EXCLUDED"}
    )
    _write_json(index_path, index)
    for name in ("atomic-capabilities.jsonl", "interaction-edges.jsonl", "batch-queue.jsonl",
                 "semantic-decisions.jsonl"):
        (ledger / name).parent.mkdir(parents=True, exist_ok=True)
        (ledger / name).touch(exist_ok=True)
    completion_path = ledger / "completion.json"
    if not completion_path.exists():
        _write_json(completion_path, {
            "schema_version": 1,
            "status": "INCOMPLETE",
            "counts": {key: 0 for key in (
                "implementation", "integration", "tests", "live", "protocol",
                "private_authorization", "parity", "superiority",
            )},
            "source_obligations": {"total": len(index["semantic_coverage"]), "unresolved": len(index["semantic_coverage"])},
        })
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    unresolved = sum(
        1 for item in index["semantic_coverage"]
        if item.get("resolution") not in {"MAPPED", "EXCLUDED"}
    )
    completion["source_obligations"] = {
        "total": len(index["semantic_coverage"]),
        "unresolved": unresolved,
    }
    if unresolved:
        completion["status"] = "INCOMPLETE"
    _write_json(completion_path, completion)
    return index


def _summary_findings(findings: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(item.get("code", "UNKNOWN")) for item in findings).items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--typescript-module", type=Path, default=None,
                        help="Path to the pinned checkout's typescript/lib/typescript.js")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--scan", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.scan:
            index = scan_to_ledger(args.source, args.ledger, typescript_module=args.typescript_module)
            print(json.dumps({"mode": "scan", **index["summary"], "head": index["source"]["head"]}, sort_keys=True))
            return 0
        index_path = args.ledger / "source-index.json"
        if not index_path.is_file():
            print("source-index.json is missing", file=sys.stderr)
            return 2
        baseline = json.loads(index_path.read_text(encoding="utf-8"))
        findings = check_source_index(
            args.source, baseline,
            atomic_rows=_read_jsonl(args.ledger / "atomic-capabilities.jsonl"),
            interaction_rows=_read_jsonl(args.ledger / "interaction-edges.jsonl"),
            typescript_module=args.typescript_module,
        )
        summary = _summary_findings(findings)
        print(json.dumps({"mode": "check", "finding_count": len(findings), "findings_by_code": summary}, sort_keys=True))
        return 0 if not findings else 1
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        print(f"audit failed: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
