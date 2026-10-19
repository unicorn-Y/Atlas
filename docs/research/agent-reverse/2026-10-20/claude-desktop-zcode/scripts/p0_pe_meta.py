import json
import os
import re
import struct
import subprocess

ROOT = r"D:\Atlas\_research\claude-desktop\2026-10-20\extract"
TARGETS = [
    "app/claude.exe",
    "app/resources/cowork-svc.exe",
    "app/resources/github-mcp/github-mcp-server.exe",
    "app/resources/claude-ssh-broker.exe",
    "app/resources/claude-ssh-proxy.exe",
    "app/resources/claude-ssh-askpass.exe",
    "app/resources/chrome-native-host.exe",
    "app/resources/app.asar.unpacked/node_modules/%40ant/claude-native/claude-native-binding.node",
    "app/resources/app.asar.unpacked/node_modules/node-pty/prebuilds/win32-x64/conpty.node",
]

ps = """
$p = '%s'
$i = Get-Item -LiteralPath $p
$v = $i.VersionInfo
$s = Get-AuthenticodeSignature -LiteralPath $p
[PSCustomObject]@{FileVersion=$v.FileVersion;ProductVersion=$v.ProductVersion;Company=$v.CompanyName;Desc=$v.FileDescription;Orig=$v.OriginalFilename;Copyright=$v.LegalCopyright;SigStatus=[string]$s.Status;Signer=if($s.SignerCertificate){$s.SignerCertificate.Subject}else{''}} | ConvertTo-Json -Compress
"""

rows = []
for t in TARGETS:
    p = os.path.join(ROOT, t.replace("/", os.sep))
    if not os.path.exists(p):
        rows.append({"path": t, "error": "MISSING"})
        continue
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps % p],
                         capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        d = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        d = {"raw": out.stdout.strip()[:300], "err": out.stderr.strip()[:300]}
    d["path"] = t
    rows.append(d)

with open(r"D:\Atlas\_research\claude-desktop\2026-10-20\index\PE-VERSION-SIGNATURE.json", "w", encoding="utf-8") as f:
    json.dump(rows, f, indent=2, ensure_ascii=False)
for r in rows:
    print(json.dumps(r, ensure_ascii=False))

# Go build info scan (Go binaries embed "go1.xx" buildinfo)
print("\n=== GO BUILDINFO ===")
for t in TARGETS:
    p = os.path.join(ROOT, t.replace("/", os.sep))
    if not os.path.exists(p):
        continue
    with open(p, "rb") as f:
        blob = f.read()
    hits = re.findall(rb"go1\.\d+(?:\.\d+)?", blob)
    m = re.search(rb"Go buildinf:", blob)
    ver = sorted(set(h.decode() for h in hits))
    if hits or m:
        print("%-70s %s buildinf=%s" % (t, ver[:3], bool(m)))
