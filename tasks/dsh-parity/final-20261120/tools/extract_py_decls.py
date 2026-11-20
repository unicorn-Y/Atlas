# -*- coding: utf-8 -*-
"""Extract Atlas Python product declarations to JSONL."""
import ast, io, json, os, re, sys

ROOT = r"D:\Atlas"
OUT = r"D:\Atlas\tasks\dsh-parity\final-20261120\_atlas_py_decls.jsonl"
SKIP = {"__pycache__", "_vendor", "tests", "test", "node_modules", "dist", "build"}


def layer_of(rel):
    if "/tests/" in rel or rel.startswith("core/tests/"):
        return "测试基座"
    return "产品运行面"


def sig(args):
    try:
        return ast.unparse(args)[:300]
    except Exception:
        return ""


def doc_of(node):
    d = ast.get_docstring(node, clean=True) or ""
    return re.sub(r"\s+", " ", d)[:400]


def decs(node):
    out = []
    for d in getattr(node, "decorator_list", []) or []:
        try:
            out.append(ast.unparse(d)[:120])
        except Exception:
            pass
    return " ".join(out)


rows = []
files = []
for dp, dn, fn in os.walk(os.path.join(ROOT, "core", "atlas")):
    dn[:] = [d for d in dn if d not in SKIP]
    for f in fn:
        if f.endswith(".py"):
            files.append(os.path.join(dp, f))
files.sort()

for path in files:
    rel = os.path.relpath(path, ROOT).replace("\\", "/")
    try:
        tree = ast.parse(io.open(path, encoding="utf-8", errors="replace").read(), filename=path)
    except SyntaxError:
        continue
    pkg_dir = os.path.dirname(rel)
    base = {"product": "Atlas", "package": "atlas." + pkg_dir.split("/", 2)[-1].replace("/", ".") if pkg_dir.startswith("core/atlas") else os.path.basename(pkg_dir),
            "package_dir": pkg_dir, "file": rel, "layer": layer_of(rel), "dts": False}

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            rows.append({**base, "kind": "函数", "symbol": node.name, "parent": "",
                         "signature": sig(node.args), "decorators": decs(node), "doc": doc_of(node),
                         "line": node.lineno, "exported": True})
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            rows.append({**base, "kind": "类", "symbol": node.name, "parent": "",
                         "signature": "", "decorators": decs(node), "doc": doc_of(node),
                         "line": node.lineno, "exported": True})
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    is_prop = any(("property" in (decs(m) or "")) for _ in [0]) or any(
                        isinstance(d, ast.Name) and d.id == "property" for d in m.decorator_list)
                    if m.name.startswith("_") and m.name != "__init__":
                        continue
                    kind = "构造函数" if m.name == "__init__" else ("属性" if is_prop else "方法")
                    rows.append({**base, "kind": kind, "symbol": node.name + "." + m.name, "parent": node.name,
                                 "signature": sig(m.args), "decorators": decs(m), "doc": doc_of(m),
                                 "line": m.lineno, "exported": False})

with io.open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(json.dumps({"product": "Atlas", "files": len(files), "rows": len(rows), "out": OUT}))