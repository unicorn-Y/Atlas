from __future__ import annotations

import ast
from pathlib import Path


def _source_tree() -> tuple[Path, ast.Module, ast.AsyncFunctionDef]:
    script = Path(__file__).resolve().parents[1] / "f1_language_smoke.py"
    tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
    run = next(
        node for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_run"
    )
    return script, tree, run


def test_hermes_home_isolation_is_set_before_any_atlas_import_and_reported():
    _, _, run = _source_tree()
    assignments = [node for node in ast.walk(run) if isinstance(node, ast.Assign)]
    hermes_root = next(
        node for node in assignments
        if any(isinstance(target, ast.Name) and target.id == "hermes_home_root"
               for target in node.targets)
    )
    assert isinstance(hermes_root.value, ast.BinOp)
    assert isinstance(hermes_root.value.left, ast.Name)
    assert hermes_root.value.left.id == "isolation_root"
    assert isinstance(hermes_root.value.op, ast.Div)
    assert isinstance(hermes_root.value.right, ast.Constant)
    assert hermes_root.value.right.value == "hermes-home"

    hermes_env = next(
        node for node in assignments
        if any(
            isinstance(target, ast.Subscript)
            and isinstance(target.value, ast.Attribute)
            and isinstance(target.value.value, ast.Name)
            and target.value.value.id == "os"
            and target.value.attr == "environ"
            and isinstance(target.slice, ast.Constant)
            and target.slice.value == "HERMES_HOME"
            for target in node.targets
        )
    )
    assert ast.unparse(hermes_env.value) == "str(hermes_home_root)"

    atlas_import_lines = [
        node.lineno for node in ast.walk(run)
        if (isinstance(node, ast.ImportFrom) and (node.module or "").startswith("atlas"))
        or (isinstance(node, ast.Import) and any(alias.name.startswith("atlas") for alias in node.names))
    ]
    assert atlas_import_lines
    assert hermes_env.lineno < min(atlas_import_lines)

    reported_roots = next(
        keyword.value for node in ast.walk(run) if isinstance(node, ast.Call)
        for keyword in node.keywords if keyword.arg == "isolated_roots"
    )
    assert isinstance(reported_roots, ast.Dict)
    assert any(
        isinstance(key, ast.Constant) and key.value == "HERMES_HOME"
        and ast.unparse(value) == "str(hermes_home_root)"
        for key, value in zip(reported_roots.keys, reported_roots.values)
    )
