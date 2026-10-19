#!/usr/bin/env python3
"""P6: env-var surface, MCP/extension lifecycle, worker inventory."""
import json
import os
import re

ASAR = r"D:\Atlas\_research\claude-desktop\2026-10-20\extract\_asar"
OUT = r"D:\Atlas\_research\claude-desktop\2026-10-20\index"
BUILD = os.path.join(ASAR, ".vite", "build")

# ---- env vars: collect with the file that references them ----
fam = re.compile(r"\b((?:CLAUDE_CODE|ANTHROPIC|CLAUDE|COWORK|MCP|OTEL)_[A-Z0-9_]+)\b")
envmap = {}
for root, _, fs in os.walk(ASAR):
    for f in fs:
        if not re.search(r"\.(js|mjs|ts|json|html)$", f):
            continue
        p = os.path.join(root, f)
        try:
            src = open(p, encoding="utf-8", errors="ignore").read()
        except Exception:
            continue
        rel = os.path.relpath(p, ASAR).replace(os.sep, "/")
        for m in fam.finditer(src):
            envmap.setdefault(m.group(1), set()).add(rel)

rows = sorted(envmap.items())
with open(os.path.join(OUT, "ENV-VARS.tsv"), "w", encoding="utf-8", newline="") as fh:
    fh.write("var\tfamily\tfile_count\tfiles\n")
    for k, files in rows:
        pre = k.split("_")[0]
        fh.write("%s\t%s\t%d\t%s\n" % (k, pre, len(files), " | ".join(sorted(files)[:6])))
print("env vars:", len(rows))

# ---- MCP: service methods from eipc, plus file anchors ----
svc = [l.rstrip("\n").split("\t") for l in open(os.path.join(OUT, "EIPC-METHODS.tsv"), encoding="utf-8")][1:]
mcpsvcs = {"MCP", "PluginBridgeMcp", "Extensions", "CustomPlugins", "LocalPlugins", "Skills",
           "Custom3pSetup", "Custom3pUsage", "Custom3pHelperRun"}
with open(os.path.join(OUT, "MCP-EXTENSION-SURFACE.tsv"), "w", encoding="utf-8", newline="") as fh:
    fh.write("service\tmethod\tparams\tfile\n")
    for r in svc:
        if r[1] in mcpsvcs:
            fh.write("\t".join([r[1], r[2], r[3], r[0]]) + "\n")
print("mcp/extension methods:", sum(1 for r in svc if r[1] in mcpsvcs))

# ---- worker inventory with bytes ----
workers = []
for d in sorted(os.listdir(BUILD)):
    p = os.path.join(BUILD, d)
    if os.path.isdir(p):
        files = []
        total = 0
        for r, _, fs in os.walk(p):
            for f in fs:
                fp = os.path.join(r, f)
                files.append((os.path.relpath(fp, BUILD).replace(os.sep, "/"), os.path.getsize(fp)))
                total += os.path.getsize(fp)
        workers.append((d, len(files), total, files))
with open(os.path.join(OUT, "WORKERS.tsv"), "w", encoding="utf-8", newline="") as fh:
    fh.write("worker_dir\tfile_count\tbytes\tfiles\n")
    for d, n, t, files in workers:
        fh.write("%s\t%d\t%d\t%s\n" % (d, n, t, " | ".join(f for f, _ in files)))
print("worker dirs:", len(workers))
for d, n, t, files in workers:
    print("  %-28s %2d files %10d B" % (d, n, t))
