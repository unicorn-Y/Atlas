# Static check: every "from atlas.X import name" resolves to a real module/name.
# Catches incomplete ports (lazy in-function imports that tests never execute).
# Usage: python scripts/diag/import_check.py core
import ast, pathlib, sys
root = pathlib.Path(sys.argv[1])  # core dir
def module_path(mod):
    p = root / pathlib.Path(*mod.split("."))
    if (p / "__init__.py").exists(): return p / "__init__.py"
    if p.with_suffix(".py").exists(): return p.with_suffix(".py")
    return None
defs_cache = {}
def top_names(path):
    if path in defs_cache: return defs_cache[path]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = set(); star = False
    for n in ast.walk(tree) if False else tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)): names.add(n.name)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                for x in ast.walk(t):
                    if isinstance(x, ast.Name): names.add(x.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "*": star = True
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, (ast.If, ast.Try)):
            for x in ast.walk(n):
                if isinstance(x, (ast.FunctionDef, ast.ClassDef)): names.add(x.name)
                if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store): names.add(x.id)
                if isinstance(x, (ast.Import, ast.ImportFrom)):
                    for a in x.names: names.add((a.asname or a.name).split(".")[0])
    defs_cache[path] = (names, star)
    return names, star
bad = []
for f in (root / "atlas").rglob("*.py"):
    try: tree = ast.parse(f.read_text(encoding="utf-8"))
    except Exception as e: bad.append((f, "PARSE", str(e))); continue
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.level == 0 and n.module.startswith("atlas."):
            mp = module_path(n.module)
            if mp is None:
                sub = None
                bad.append((f, n.lineno, f"module {n.module} missing")); continue
            names, star = top_names(mp)
            for a in n.names:
                if a.name == "*" or a.name in names: continue
                if module_path(n.module + "." + a.name): continue
                if star: continue
                bad.append((f.relative_to(root), n.lineno, f"{n.module}.{a.name}"))
for b in bad: print(*b)
print("TOTAL", len(bad))
