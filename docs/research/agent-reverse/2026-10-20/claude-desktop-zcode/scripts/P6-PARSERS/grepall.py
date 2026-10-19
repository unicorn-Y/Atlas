#!/usr/bin/env python3
"""grepall.py PATTERN [dir] [max_per_file] [ctx]
Byte-offset aware grep across the extracted build tree. Read-only."""
import sys, os

def main():
    pat = sys.argv[1]
    root = sys.argv[2] if len(sys.argv) > 2 else r"D:\Atlas\_research\claude-desktop\2026-10-20\extract\_asar"
    maxper = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    ctx = int(sys.argv[4]) if len(sys.argv) > 4 else 120
    needle = pat.encode('utf-8')
    total = 0
    for dp, dn, fn in os.walk(root):
        for f in fn:
            if not f.lower().endswith(('.js','.mjs','.cjs','.json','.html','.ts','.css')):
                continue
            p = os.path.join(dp, f)
            try:
                data = open(p, 'rb').read()
            except Exception:
                continue
            idxs = []
            start = 0
            while len(idxs) < maxper:
                i = data.find(needle, start)
                if i < 0: break
                idxs.append(i); start = i + 1
            for i in idxs:
                total += 1
                lo = max(0, i-ctx); hi = min(len(data), i+len(needle)+ctx)
                s = data[lo:hi].decode('utf-8', 'replace').replace('\n','\\n')
                rel = os.path.relpath(p, root)
                print(f"{rel}@{i}\t{s}")
    print(f"# total hits shown: {total}")

if __name__ == '__main__':
    main()
