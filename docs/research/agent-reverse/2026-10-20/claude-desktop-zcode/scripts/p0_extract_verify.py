#!/usr/bin/env python3
"""Extract original MSIX into an independent tree, verify hashes against the ledger,
and diff against the previously archived 4443-row baseline."""
import hashlib
import json
import os
import zipfile

MSIX = r"D:\Atlas-Reverse-Lab\claude-desktop\input\claude-desktop-x64-2bf309665f.msix"
ROOT = r"D:\Atlas\_research\claude-desktop\2026-10-20"
EX = os.path.join(ROOT, "extract")
OUT = os.path.join(ROOT, "index")
BASE = r"D:\atlas-anatomy-zcode\docs\research\agent-reverse\2026-10-19\claude-desktop\evidence\msix-tree.tsv"

os.makedirs(EX, exist_ok=True)
z = zipfile.ZipFile(MSIX)
n = 0
for info in z.infolist():
    if info.is_dir():
        continue
    dest = os.path.join(EX, info.filename.replace("/", os.sep))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with z.open(info) as src, open(dest, "wb") as dst:
        while True:
            b = src.read(1 << 20)
            if not b:
                break
            dst.write(b)
    n += 1
print("extracted", n)

# verify against our own ledger
led = {}
with open(os.path.join(OUT, "FILE-LEDGER.tsv"), encoding="utf-8") as f:
    next(f)
    for line in f:
        c = line.rstrip("\n").split("\t")
        led[c[3]] = (int(c[5]), c[7])

mism = []
for p, (size, sha) in led.items():
    fp = os.path.join(EX, p.replace("/", os.sep))
    if not os.path.exists(fp):
        mism.append((p, "MISSING", "", size, sha))
        continue
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
    if h.hexdigest() != sha or os.path.getsize(fp) != size:
        mism.append((p, "HASH_OR_SIZE", h.hexdigest(), size, sha))
print("verify mismatches:", len(mism))
if mism:
    print(mism[:10])

# diff against prior baseline
base = {}
with open(BASE, encoding="utf-8-sig") as f:
    next(f)
    for line in f:
        c = line.rstrip("\n").split("\t")
        if len(c) >= 3:
            base[c[0]] = (c[1], c[2])
ours = {p: (str(s), sh) for p, (s, sh) in led.items()}
added = sorted(set(ours) - set(base))
removed = sorted(set(base) - set(ours))
changed = sorted(p for p in set(ours) & set(base) if ours[p] != base[p])
rows = []
for p in added:
    rows.append(["ADDED", p, ours[p][0], ours[p][1], "", ""])
for p in removed:
    rows.append(["REMOVED", p, "", "", base[p][0], base[p][1]])
for p in changed:
    rows.append(["CHANGED", p, ours[p][0], ours[p][1], base[p][0], base[p][1]])
with open(os.path.join(OUT, "P0-DIFF-VS-2026-10-19.tsv"), "w", encoding="utf-8", newline="") as f:
    f.write("status\tpath\tours_bytes\tours_sha256\tbaseline_bytes\tbaseline_sha256\n")
    for r in rows:
        f.write("\t".join(r) + "\n")
print("diff added/removed/changed:", len(added), len(removed), len(changed))
print("baseline rows:", len(base), "ours:", len(ours))
