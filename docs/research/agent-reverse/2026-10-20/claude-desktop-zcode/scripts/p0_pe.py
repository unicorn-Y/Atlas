import os
import struct

ROOT = r"D:\Atlas\_research\claude-desktop\2026-10-20\extract"
OUT = r"D:\Atlas\_research\claude-desktop\2026-10-20\index\PE-BINARIES.tsv"


def pe_info(p):
    try:
        with open(p, "rb") as f:
            d = f.read(0x1000)
    except Exception:
        return None
    if d[:2] != b"MZ" or len(d) < 0x40:
        return None
    off = struct.unpack("<I", d[0x3C:0x40])[0]
    if d[off:off + 4] != b"PE\x00\x00":
        return None
    mach = struct.unpack("<H", d[off + 4:off + 6])[0]
    magic = struct.unpack("<H", d[off + 24:off + 26])[0]
    sub = struct.unpack("<H", d[off + 92:off + 94])[0]
    return {
        "arch": {0x8664: "x64", 0x14C: "x86", 0xAA64: "arm64"}.get(mach, hex(mach)),
        "pe32plus": magic == 0x20B,
        "subsystem": {2: "GUI", 3: "CUI"}.get(sub, str(sub)),
    }


rows = []
for root, _, fs in os.walk(ROOT):
    for f in fs:
        p = os.path.join(root, f)
        try:
            if open(p, "rb").read(2) != b"MZ":
                continue
        except Exception:
            continue
        i = pe_info(p)
        if i is None:
            continue
        rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
        rows.append((rel, os.path.getsize(p), i))
rows.sort()
with open(OUT, "w", encoding="utf-8", newline="") as f:
    f.write("path\tbytes\tarch\tpe32plus\tsubsystem\n")
    for p, s, i in rows:
        f.write("%s\t%d\t%s\t%s\t%s\n" % (p, s, i["arch"], i["pe32plus"], i["subsystem"]))
print("PE count", len(rows))
for p, s, i in rows:
    print("%12d %6s %4s %s" % (s, i["arch"], i["subsystem"], p))
