#!/usr/bin/env python3
"""Build ARCHIVE-NESTING.tsv and PACKAGE-MANIFEST.tsv from the independent ledger."""
import csv
import hashlib
import json
import os
import zipfile

ROOT = r"D:\Atlas\_research\claude-desktop\2026-10-20"
IDX = os.path.join(ROOT, "index")
MSIX = r"D:\Atlas-Reverse-Lab\claude-desktop\input\claude-desktop-x64-2bf309665f.msix"
EX = os.path.join(ROOT, "extract")

z = zipfile.ZipFile(MSIX)
infos = z.infolist()

nest = []


def add(nid, container, inner, kind, bytes_, sha):
    nest.append([nid, container, inner, kind, str(bytes_), sha])


add("N-0001", "claude-desktop-x64-2bf309665f.msix", "-", "root-msix", os.path.getsize(MSIX),
    "2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee")

# nested zip-like members inside MSIX
for i in infos:
    lp = i.filename.lower()
    if lp.endswith((".skill", ".nupkg", ".zip", ".asar", ".pak", ".pri", ".dat", ".bin", ".node", ".dll", ".exe", ".wasm", ".jsc")):
        pass

# enumerate skill inner
skill_dir = os.path.join(EX, "_asar", "resources", "bundled-skills")
n = 2
for fn in sorted(os.listdir(skill_dir)):
    if not fn.endswith(".skill"):
        continue
    p = os.path.join(skill_dir, fn)
    h = hashlib.sha256(open(p, "rb").read()).hexdigest()
    add("N-%04d" % n, "app.asar:resources/bundled-skills/" + fn, "-", "skill-zip-root",
        os.path.getsize(p), h)
    n += 1
    zz = zipfile.ZipFile(p)
    for ii in zz.infolist():
        if ii.is_dir():
            continue
        d = zz.read(ii)
        add("N-%04d" % n, fn, ii.filename, "skill-inner-file", ii.file_size,
            hashlib.sha256(d).hexdigest())
        n += 1

# artifacts libs are plain files inside asar -> record containerization
for sub in ["resources/artifact-libs", "resources/office365-mcp", "resources/github-mcp"]:
    base = os.path.join(EX, "_asar", sub.replace("/", os.sep))
    if not os.path.isdir(base):
        continue
    for root, _, fs in os.walk(base):
        for f in sorted(fs):
            p = os.path.join(root, f)
            rel = os.path.relpath(p, os.path.join(EX, "_asar")).replace(os.sep, "/")
            add("N-%04d" % n, "app.asar", rel, "asar-member-binary-or-lib",
                os.path.getsize(p), hashlib.sha256(open(p, "rb").read()).hexdigest())
            n += 1

with open(os.path.join(IDX, "ARCHIVE-NESTING.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["id", "container", "inner_path", "kind", "bytes", "sha256"])
    for r in nest:
        w.writerow(r)
print("nesting rows", len(nest))

# PACKAGE-MANIFEST: one row per delivered artifact + identity
arts = [
    ["PKG-01", "MSIX", "claude-desktop-x64-2bf309665f.msix", "enterprise/store", "x64", "windows",
     str(os.path.getsize(MSIX)), "2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee",
     "2.42304.0", "fixed baseline; AppxManifest Identity.Version=2.42304.0.0"],
    ["PKG-02", "nupkg", r"D:\_deliverables\claude-desktop-2.42304.2\AnthropicClaude-2.42304.2-full.nupkg",
     "squirrel/enterprise", "x64", "windows", "262853497", "PENDING", "2.42304.2",
     "local full nupkg; asar package.json says 2.42304.2"],
    ["PKG-03", "setup-exe", r"D:\_claude_desktop\Claude-Setup-x64.exe", "squirrel-bootstrapper", "x64",
     "windows", "132098208", "PENDING", "0.14.10-channel", "Squirrel setup; downloads RELEASES chain"],
    ["PKG-04", "nupkg", r"D:\_claude_desktop\AnthropicClaude-0.14.10-full.nupkg", "squirrel/consumer",
     "x64", "windows", "131185172", "PENDING", "0.14.10",
     "matches official RELEASES.txt last line for nest-win-x64"],
]
with open(os.path.join(IDX, "PACKAGE-MANIFEST.tsv"), "w", encoding="utf-8", newline="") as f:
    w = csv.writer(f, delimiter="\t")
    w.writerow(["id", "format", "path", "channel", "arch", "platform", "bytes", "sha256",
                "product_version", "notes"])
    for r in arts:
        w.writerow(r)
print("manifest rows", len(arts))
