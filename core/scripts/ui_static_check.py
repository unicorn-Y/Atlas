"""Static guards for renderer mistakes that only show up as a blank window at runtime.

Each rule here comes from a real acceptance failure:
- duplicate slash-command ids make App.tsx throw on first render (U9c: two `/status`);
- a lazy() component rendered outside <Suspense> blanks the page the first time it mounts (U5);
- a preference read and written under different keys silently never takes effect (U6 `/vim`).
Run: python core/scripts/ui_static_check.py   (last line: UI STATIC CHECK PASS)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENDERER = ROOT / "frontend" / "src" / "renderer"
problems: list[str] = []

app = (RENDERER / "App.tsx").read_text(encoding="utf-8")

ids = re.findall(r"\{ id: '([^']+)', label: '/", app)
seen: dict[str, int] = {}
for command_id in ids:
    seen[command_id] = seen.get(command_id, 0) + 1
for command_id, count in seen.items():
    if count > 1:
        problems.append(f"duplicate slash command id '{command_id}' ({count}x) in App.tsx — the app throws on render")

for path in sorted(RENDERER.rglob("*.tsx")):
    text = path.read_text(encoding="utf-8")
    lazy_names = re.findall(r"const (\w+) = lazy\(", text)
    if not lazy_names:
        continue
    depth = 0
    for number, line in enumerate(text.split("\n"), 1):
        opens = len(re.findall(r"<Suspense\b[^>]*?(?<!/)>", line))
        closes = line.count("</Suspense>")
        inside = depth > 0 or opens > 0
        for name in lazy_names:
            # Assignments like `const x = <Lazy .../>` are rendered elsewhere; only flag JSX children.
            if re.search(r"<" + name + r"[\s/>]", line) and not inside and not re.match(r"\s*const \w+ = ", line):
                problems.append(f"{path.relative_to(ROOT)}:{number} lazy component <{name}> rendered outside <Suspense>")
        depth += opens - closes

pref_reads = set(re.findall(r"localStorage\.getItem\('atlas\.([a-z0-9.-]+)'\)", "\n".join(
    p.read_text(encoding="utf-8") for p in RENDERER.rglob("*.tsx"))))
pref_writes = set(re.findall(r"setPref\('([a-z0-9-]+)'", app))
for key in pref_writes:
    if f"preference.{key}" not in pref_reads and key in {k.split(".")[-1] for k in pref_reads if not k.startswith("preference.")}:
        problems.append(f"preference '{key}' is written as atlas.preference.{key} but read under a different key")

# Backend: subprocess calls decoding text without an explicit encoding use the Windows ANSI code page;
# Chinese paths/output then make the reader thread fail and stdout becomes None (workspace search 500,
# git status, worker diffs all broke this way).
import ast  # noqa: E402

for path in sorted((ROOT / "core" / "atlas").rglob("*.py")):
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        if name not in {"run", "check_output", "Popen", "call", "check_call"}:
            continue
        keywords = {kw.arg: kw for kw in node.keywords if kw.arg}
        text_kw = keywords.get("text") or keywords.get("universal_newlines")
        if (text_kw is not None and isinstance(text_kw.value, ast.Constant) and text_kw.value.value is True
                and "encoding" not in keywords):
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno} subprocess {name}(text=True) without encoding=\"utf-8\"")

if problems:
    print("\n".join(problems))
    sys.exit(1)
print("UI STATIC CHECK PASS")
