#!/usr/bin/env python3
"""ctx.py FILE PATTERN [before] [after] [maxhits]
Print byte offsets and context for a literal pattern. Read-only."""
import sys, os

def main():
    path = sys.argv[1]
    pat = sys.argv[2]
    before = int(sys.argv[3]) if len(sys.argv) > 3 else 300
    after = int(sys.argv[4]) if len(sys.argv) > 4 else 300
    maxhits = int(sys.argv[5]) if len(sys.argv) > 5 else 20
    data = open(path, 'rb').read()
    needle = pat.encode('utf-8')
    start = 0
    n = 0
    while True:
        i = data.find(needle, start)
        if i < 0:
            break
        n += 1
        lo = max(0, i - before)
        hi = min(len(data), i + after)
        chunk = data[lo:hi].decode('utf-8', errors='replace')
        print(f"--- hit {n} @offset {i} (0x{i:x}) in {os.path.basename(path)} ---")
        print(chunk.replace('\x00', '.'))
        print()
        if n >= maxhits:
            print("... (truncated at maxhits)")
            break
        start = i + 1
    print(f"TOTAL HITS: {n}")

if __name__ == '__main__':
    main()
