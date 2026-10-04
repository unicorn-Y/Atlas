"""Live scenario 05 checker: four rounds of constraints, round-1 constraint still held."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])

EXPECTED = ["* RULE-ONE *", "RULE-TWO-7", "RULE-THREE!", "RULE-FOUR"]
problems = []
poem = WS / "poem.txt"
if not poem.is_file():
    problems.append("poem.txt missing")
else:
    lines = [ln.strip() for ln in poem.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if lines != EXPECTED:
        problems.append(f"poem.txt lines mismatch: {lines!r} != {EXPECTED!r}")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
