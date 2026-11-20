#!/usr/bin/env python3
"""Parse scanned shell files without executing them."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

try:
    from tree_sitter import Language, Parser
    import tree_sitter_bash
except ImportError:  # A missing pinned grammar must never look like semantic coverage.
    Language = Parser = tree_sitter_bash = None  # type: ignore[assignment]


CONTROL_FLOW_TYPES = {
    "case_statement", "for_statement", "if_statement", "select_statement",
    "until_statement", "while_statement",
}
PLATFORM_TOKENS = ("BASH_VERSION", "MACHTYPE", "MSYSTEM", "OSTYPE", "uname", "win32", "linux", "darwin")


def _literal_argument(node: Any, source: bytes) -> str | None:
    raw = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace").strip()
    if node.type not in {"word", "string", "raw_string", "number"} or not raw:
        return None
    if any(token in raw for token in ("$", "`", "$(", "<(", ">(")):
        return None
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in {"'", '"'}:
        raw = raw[1:-1]
    return raw if raw else None


def _ast_contracts(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if Parser is None or Language is None or tree_sitter_bash is None:
        return [], []

    source = text.encode("utf-8", errors="replace")
    syntax_tree = Parser(Language(tree_sitter_bash.language())).parse(source)
    if syntax_tree.root_node.has_error:
        diagnostics: list[dict[str, Any]] = []
        pending = [syntax_tree.root_node]
        while pending:
            node = pending.pop()
            if node.type == "ERROR" or node.is_missing:
                diagnostics.append({
                    "line": node.start_point.row + 1,
                    "reason_digest": hashlib.sha256(source[node.start_byte:node.end_byte]).hexdigest(),
                })
            pending.extend(reversed(node.children))
        if not diagnostics:
            diagnostics.append({"line": 0, "reason_digest": hashlib.sha256(source).hexdigest()})
        return [], diagnostics

    contracts: list[dict[str, Any]] = []
    stack: list[tuple[Any, str | None]] = [(syntax_tree.root_node, None)]
    while stack:
        node, enclosing_function = stack.pop()
        current_function = enclosing_function
        span = {"start_line": node.start_point.row + 1, "end_line": node.end_point.row + 1}
        if node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            name = (source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
                    if name_node else "<dynamic>")
            body_node = node.child_by_field_name("body")
            contracts.append({
                "kind": "bash_function",
                "name": name,
                "source_span": span,
                "body_node_type": body_node.type if body_node else None,
            })
            current_function = name
        elif node.type in CONTROL_FLOW_TYPES:
            contract: dict[str, Any] = {
                "kind": "bash_control_flow",
                "node_type": node.type,
                "function": current_function,
                "source_span": span,
            }
            fragment = source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
            platform_tokens = sorted({
                token for token in PLATFORM_TOKENS
                if re.search(rf"(?<![A-Za-z0-9_]){re.escape(token)}(?![A-Za-z0-9_])", fragment, re.IGNORECASE)
            })
            if platform_tokens:
                contracts.append({
                    "kind": "bash_platform_condition",
                    "tokens": platform_tokens,
                    "function": current_function,
                    "source_span": span,
                    "condition_digest": hashlib.sha256(fragment.encode("utf-8", errors="replace")).hexdigest(),
                })
            contracts.append(contract)
        elif node.type == "command":
            command_node = node.child_by_field_name("name")
            command = (source[command_node.start_byte:command_node.end_byte].decode("utf-8", errors="replace")
                       if command_node else "")
            arguments = [
                child for index, child in enumerate(node.children)
                if node.field_name_for_child(index) == "argument"
            ]
            literal_arguments = [_literal_argument(argument, source) for argument in arguments]
            args_digest = hashlib.sha256(b"\0".join(
                source[argument.start_byte:argument.end_byte] for argument in arguments
            )).hexdigest()
            if re.fullmatch(r"[A-Za-z0-9_./+-]+", command):
                contracts.append({
                    "kind": "bash_command",
                    "name": command,
                    "function": current_function,
                    "source_span": span,
                    "argument_count": len(arguments),
                    "arguments_digest": args_digest,
                })
            else:
                contracts.append({
                    "kind": "bash_dynamic_command_unresolved",
                    "function": current_function,
                    "source_span": span,
                    "command_digest": hashlib.sha256(command.encode("utf-8", errors="replace")).hexdigest(),
                })
            if command == "set":
                contracts.append({
                    "kind": "bash_shell_options",
                    "options": [value for value in literal_arguments if value is not None],
                    "dynamic_options_unresolved": any(value is None for value in literal_arguments),
                    "function": current_function,
                    "source_span": span,
                })
            elif command == "trap":
                handler = arguments[0] if arguments else None
                signal_names = [value for value in literal_arguments[1:] if value is not None]
                contracts.append({
                    "kind": "bash_trap",
                    "signals": signal_names,
                    "signal_list_complete": len(signal_names) == max(0, len(arguments) - 1),
                    "handler_digest": hashlib.sha256(
                        source[handler.start_byte:handler.end_byte] if handler else b""
                    ).hexdigest(),
                    "function": current_function,
                    "source_span": span,
                })
            elif command in {"exit", "return"}:
                status = literal_arguments[0] if literal_arguments else None
                contracts.append({
                    "kind": "bash_status_transition",
                    "transition": command,
                    "status": int(status) if status and re.fullmatch(r"\d+", status) else None,
                    "status_unresolved": bool(arguments and (status is None or not re.fullmatch(r"\d+", status))),
                    "inherits_previous_status": not arguments,
                    "function": current_function,
                    "source_span": span,
                })
            elif command in {"exec", "source", ".", "bash", "sh"}:
                target_index = next((i for i, value in enumerate(literal_arguments) if value and not value.startswith("-")), None)
                target = literal_arguments[target_index] if target_index is not None else None
                contracts.append({
                    "kind": "bash_launch_target" if target else "bash_dynamic_launch_unresolved",
                    **({"target": target, "invocation": command} if target else {
                        "target_digest": args_digest, "invocation": command,
                    }),
                    "function": current_function,
                    "source_span": span,
                })
        stack.extend((child, current_function) for child in reversed(node.children))

    contracts.sort(key=lambda item: (
        int(item["source_span"]["start_line"]),
        str(item["kind"]),
        str(item.get("name", item.get("node_type", ""))),
    ))
    return contracts, []


def parse(root: Path, paths: list[str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for relative in paths:
        text = (root / relative).read_text(encoding="utf-8", errors="replace")
        first = text.splitlines()[0] if text.splitlines() else ""
        parser_name = "sh" if "/bin/sh" in first and "bash" not in first else "bash"
        parser = shutil.which(parser_name)
        result = None
        if parser is not None:
            try:
                result = subprocess.run(
                    [parser, "-n"], input=text, capture_output=True, text=True, check=False,
                    timeout=20,
                )
            except (OSError, subprocess.SubprocessError):
                # Fall back to the pinned grammar below; a host shell executable
                # is not required to inspect source and must never be run as a script.
                result = None
        # Windows may resolve `bash` to the WSL app-execution alias.  With no
        # distro installed it exits nonzero and writes its launcher notice to
        # stdout while stderr stays empty.  That is not a shell syntax error;
        # continue to the pinned in-process grammar below, which can still
        # validate the source and report its actual error nodes.
        if result is not None and result.returncode != 0 and result.stderr.strip():
            match = re.search(r"line\s+(\d+)", result.stderr, re.IGNORECASE)
            diagnostics = [{
                "line": int(match.group(1)) if match else 0,
                "reason_digest": hashlib.sha256(result.stderr.encode("utf-8", errors="replace")).hexdigest(),
            }]
            rows.append({"path": relative, "parser": parser_name, "parse_diagnostics": diagnostics})
            continue

        if Parser is None or Language is None or tree_sitter_bash is None:
            rows.append({
                "path": relative,
                "parser": parser_name,
                "parser_status": "TREE_SITTER_BASH_UNAVAILABLE",
                "parse_diagnostics": [],
                "contracts": [{
                    "kind": "shell_syntax_only",
                    "source_span": {"start_line": 1, "end_line": max(1, len(text.splitlines()))},
                    "parse_status": "SYNTAX_VALID_SEMANTICS_UNRESOLVED",
                }],
            })
            continue

        contracts, diagnostics = _ast_contracts(text)
        if diagnostics:
            rows.append({"path": relative, "parser": parser_name, "parse_diagnostics": diagnostics})
            continue
        rows.append({
            "path": relative,
            "parser": parser_name,
            "parse_diagnostics": [],
            "contracts": [{
                "kind": "shell_syntax_only",
                "source_span": {"start_line": 1, "end_line": max(1, len(text.splitlines()))},
                "parse_status": "SYNTAX_VALID_SEMANTICS_UNRESOLVED",
            }, *contracts],
        })
    return rows


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: dsh_shell_parse.py SOURCE_ROOT")
    paths = json.loads(sys.stdin.read())
    if not isinstance(paths, list) or not all(isinstance(item, str) for item in paths):
        raise SystemExit("input must be a JSON list of relative paths")
    print(json.dumps(parse(Path(sys.argv[1]), paths), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
