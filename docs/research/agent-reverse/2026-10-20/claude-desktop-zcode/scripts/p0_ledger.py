#!/usr/bin/env python3
"""
P0 independent ledger generator.
Reads the ORIGINAL MSIX zip directly (never the previously extracted tree),
streams every entry, records size/CRC/SHA256/format/layer, and parses the
inner app.asar header to enumerate every ASAR path with offsets and hashes.
Outputs TSVs into the research directory.
"""
import hashlib
import io
import json
import os
import re
import struct
import sys
import zipfile

MSIX = r"D:\Atlas-Reverse-Lab\claude-desktop\input\claude-desktop-x64-2bf309665f.msix"
OUT = r"D:\Atlas\_research\claude-desktop\2026-10-20\index"
PKG_SHA = "2bf309665f0de4eaa76a7e64033594e6f73ceb6413c60080f72f3ce640fa24ee"
VERSION = "2.42304.0"

os.makedirs(OUT, exist_ok=True)

SIG = [
    (b"MZ", "PE"),
    (b"\x7fELF", "ELF"),
    (b"PK\x03\x04", "ZIP"),
    (b"\x1f\x8b", "GZIP"),
    (b"SQLite format 3\x00", "SQLITE"),
    (b"wOFF", "WOFF"),
    (b"wOF2", "WOFF2"),
    (b"\x89PNG", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF8", "GIF"),
    (b"<?xml", "XML"),
    (b"{\"", "JSON_OR_ASAR"),
    (b"\x28\xb5\x2f\xfd", "ZSTD"),
    (b"\x1f\x9d", "COMPRESS"),
    (b"\x00asm", "WASM"),
    (b"\xca\xfe\xba\xbe", "MACHO_FAT"),
]


def sniff(head):
    for s, name in SIG:
        if head.startswith(s):
            return name
    if head[:2] in (b"\x03\x00", b"\x04\x00"):
        return "V8JSC_OR_PYC"
    try:
        head.decode("utf-8")
        return "TEXT"
    except Exception:
        return "BINARY"


def layer_of(p):
    lp = p.lower()
    if lp.startswith("app/resources/app.asar"):
        return "asar"
    if lp.startswith("app/resources/"):
        return "resources"
    if lp.startswith("app/"):
        return "app-shell"
    if lp.startswith("assets/"):
        return "assets"
    if lp.endswith(".pri") or lp.endswith(".xml") or lp.endswith(".p7x"):
        return "package-metadata"
    return "package-other"


def ext_of(p):
    base = os.path.basename(p)
    if "." not in base:
        return "(none)"
    return base.rsplit(".", 1)[1].lower()[:12]


def main():
    z = zipfile.ZipFile(MSIX)
    infos = z.infolist()
    rows = []
    total_uncomp = 0
    for i, info in enumerate(infos):
        if info.is_dir():
            rows.append({
                "index": i, "path": info.filename, "kind": "dir",
                "size": 0, "compressed": 0, "sha256": "N/A", "crc32": "N/A",
                "format": "DIR", "layer": layer_of(info.filename), "ext": "(dir)",
            })
            continue
        h = hashlib.sha256()
        with z.open(info) as f:
            head = f.read(4096)
            h.update(head)
            while True:
                b = f.read(1 << 20)
                if not b:
                    break
                h.update(b)
        total_uncomp += info.file_size
        rows.append({
            "index": i,
            "path": info.filename,
            "kind": "file",
            "size": info.file_size,
            "compressed": info.compress_size,
            "sha256": h.hexdigest(),
            "crc32": "%08x" % info.CRC,
            "format": sniff(head),
            "layer": layer_of(info.filename),
            "ext": ext_of(info.filename),
        })

    with open(os.path.join(OUT, "FILE-LEDGER.tsv"), "w", encoding="utf-8", newline="") as f:
        cols = ["id", "product_version", "source_package_sha256", "path", "kind",
                "size", "compressed", "sha256", "crc32", "format", "layer", "ext"]
        f.write("\t".join(cols) + "\n")
        for r in rows:
            rid = "A-%05d" % r["index"]
            f.write("\t".join([rid, VERSION, PKG_SHA, r["path"], r["kind"],
                               str(r["size"]), str(r["compressed"]), r["sha256"],
                               r["crc32"], r["format"], r["layer"], r["ext"]]) + "\n")

    # summary
    by_layer = {}
    by_format = {}
    nfiles = 0
    for r in rows:
        by_layer[r["layer"]] = by_layer.get(r["layer"], 0) + 1
        by_format[r["format"]] = by_format.get(r["format"], 0) + 1
        if r["kind"] == "file":
            nfiles += 1
    summary = {
        "msix_sha256": PKG_SHA,
        "msix_bytes_on_disk": os.path.getsize(MSIX),
        "zip_entries_total": len(rows),
        "zip_files": nfiles,
        "zip_dirs": len(rows) - nfiles,
        "uncompressed_bytes_sum": total_uncomp,
        "by_layer": by_layer,
        "by_format": by_format,
        "version_claimed_from_manifest": VERSION,
    }
    with open(os.path.join(OUT, "P0-SUMMARY.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # ---- ASAR ----
    asar_info = None
    for info in infos:
        if info.filename.lower() == "app/resources/app.asar":
            asar_info = info
            break
    if asar_info is None:
        print("NO ASAR FOUND", file=sys.stderr)
        return

    with z.open(asar_info) as f:
        raw = f.read()

    asar_sha = hashlib.sha256(raw).hexdigest()
    # electron asar: 4-byte LE uint32 = 4, then pickle: uint32 size, uint32 headerlen...
    magic = struct.unpack("<I", raw[:4])[0]
    assert magic == 4, "bad asar magic %r" % magic
    hdr_size = struct.unpack("<I", raw[4:8])[0]
    # pickle payload: uint32 payload_size, uint32 string_len, then utf-8 JSON
    hdr_str_size = struct.unpack("<I", raw[12:16])[0]
    header_json = raw[16:16 + hdr_str_size].decode("utf-8")
    header = json.loads(header_json)
    data_start = 8 + hdr_size

    files = []

    def walk(node, prefix):
        for name, meta in node.get("files", {}).items():
            full = prefix + "/" + name if prefix else name
            if "files" in meta:
                files.append({"path": full, "kind": "dir", "size": 0, "offset": "",
                              "sha256": "N/A", "unpacked": ""})
                walk(meta, full)
            else:
                unpacked = meta.get("unpacked", False)
                size = meta.get("size", 0)
                off = meta.get("offset", "")
                sha = "UNPACKED_SEPARATE"
                if not unpacked and off != "":
                    start = data_start + int(off)
                    blob = raw[start:start + int(size)]
                    sha = hashlib.sha256(blob).hexdigest()
                files.append({"path": full, "kind": "file", "size": size,
                              "offset": off, "sha256": sha,
                              "unpacked": "TRUE" if unpacked else ""})
    walk(header, "")

    with open(os.path.join(OUT, "ASAR-FILE-LEDGER.tsv"), "w", encoding="utf-8", newline="") as f:
        f.write("\t".join(["id", "product_version", "source_package_sha256",
                           "asar_sha256", "path", "kind", "size", "offset",
                           "sha256", "unpacked", "ext"]) + "\n")
        for i, r in enumerate(files):
            f.write("\t".join([
                "S-%05d" % i, VERSION, PKG_SHA, asar_sha, r["path"], r["kind"],
                str(r["size"]), str(r["offset"]), r["sha256"], r["unpacked"],
                ext_of(r["path"]) if r["kind"] == "file" else "(dir)",
            ]) + "\n")

    asar_summary = {
        "asar_sha256": asar_sha,
        "asar_bytes": len(raw),
        "header_json_bytes": hdr_str_size,
        "data_start": data_start,
        "asar_paths_total": len(files),
        "asar_files": sum(1 for r in files if r["kind"] == "file"),
        "asar_dirs": sum(1 for r in files if r["kind"] == "dir"),
        "asar_unpacked_entries": sum(1 for r in files if r["unpacked"]),
        "asar_ext_hist": {},
    }
    for r in files:
        if r["kind"] == "file":
            e = ext_of(r["path"])
            asar_summary["asar_ext_hist"][e] = asar_summary["asar_ext_hist"].get(e, 0) + 1
    with open(os.path.join(OUT, "P0-ASAR-SUMMARY.json"), "w", encoding="utf-8") as f:
        json.dump(asar_summary, f, indent=2, ensure_ascii=False)

    print(json.dumps({"msix": summary, "asar": asar_summary}, indent=2, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
