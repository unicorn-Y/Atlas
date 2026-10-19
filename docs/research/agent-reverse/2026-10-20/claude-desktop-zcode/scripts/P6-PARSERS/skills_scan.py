#!/usr/bin/env python3
"""Scan extracted skills: frontmatter, scripts, deps, entry points. Read-only."""
import os, re, json, sys

ROOT = r"D:\Atlas\_research\claude-desktop\2026-10-20\index\work-P6\skills-extracted"

def parse_frontmatter(text):
    m = re.match(r'^---\r?\n(.*?)\r?\n---', text, re.S)
    if not m:
        return {}
    fm = {}
    for line in m.group(1).splitlines():
        if ':' in line and not line.startswith(' '):
            k, v = line.split(':', 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm

def scan(skill):
    base = os.path.join(ROOT, skill, skill)
    out = {"name": skill, "files": [], "py": [], "js": [], "sh": [], "xsd": [], "md": []}
    if not os.path.isdir(base):
        return out
    for dp, dn, fn in os.walk(base):
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), base).replace('\\', '/')
            out["files"].append(rel)
            ext = os.path.splitext(f)[1].lower()
            if ext == '.py': out["py"].append(rel)
            elif ext == '.js': out["js"].append(rel)
            elif ext in ('.sh',): out["sh"].append(rel)
            elif ext == '.xsd': out["xsd"].append(rel)
            elif ext == '.md': out["md"].append(rel)
    sk = os.path.join(base, 'SKILL.md')
    if os.path.exists(sk):
        t = open(sk, encoding='utf-8', errors='replace').read()
        out["frontmatter"] = parse_frontmatter(t)
        out["lines"] = len(t.splitlines())
        out["skill_bytes"] = len(t.encode('utf-8'))
        # collect commands in code fences
        cmds = re.findall(r'^\s*(?:python3?|node|npm|pip|markitdown|pdftoppm|pdfinfo|pdffonts|pdftotext|pdfimages|pdfdetach|qpdf|pdftk|unzip|zip|pandoc|soffice|ls|find|grep|cd|rm|mkdir)\b[^\n]*', t, re.M)
        out["commands"] = sorted(set(cmds))[:40]
        out["mentions_scripts"] = sorted(set(re.findall(r'scripts/[A-Za-z0-9_./-]+\.(?:py|js)', t)))
    return out

if __name__ == '__main__':
    res = {}
    for s in ["docx", "pdf", "pdf-reading", "pptx", "xlsx", "frontend-design"]:
        res[s] = scan(s)
    print(json.dumps(res, indent=1)[:40000])
