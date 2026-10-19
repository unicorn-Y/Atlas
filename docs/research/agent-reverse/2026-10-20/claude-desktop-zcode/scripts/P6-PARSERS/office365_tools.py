#!/usr/bin/env python3
"""Extract office365 MCP tool declarations (name/description/offset) from the bundle."""
import re, json, sys

PATH = r"D:/Atlas/_research/claude-desktop/2026-10-20/extract/_asar/resources/office365-mcp/office365-mcp-stdio.mjs"

def main():
    s = open(PATH, encoding='utf-8', errors='replace').read()
    rows = []
    # class-field style: name="tool";description="..."  (description may be a template literal)
    for m in re.finditer(r'name="([a-z0-9_]{3,60})"', s):
        name = m.group(1)
        pos = m.start()
        window = s[pos:pos+4000]
        d = re.search(r'description=(?:"([^"]{0,600})"|`([^`]{0,600})`)', window)
        desc = (d.group(1) or d.group(2)) if d else ""
        # detect readOnlyHint nearby (within 6000 chars)
        ro = s.find('readOnlyHint:!0', pos, pos+6000) != -1
        rows.append({"name": name, "offset": pos, "description": desc.strip(), "read_only": ro})
    print(json.dumps(rows, indent=1))

if __name__ == '__main__':
    main()
