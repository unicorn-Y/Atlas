"""Live scenario 06 checker: three artifacts correct (task survived auto-compaction)."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])

TOTAL_LOG_LINES = 4000
CODE_EVERY = 160
CODE_BASE = 1000
MAGIC = "6174"
EXPECTED_CODES = [f"KEY-{CODE_BASE + i}" for i in range(TOTAL_LOG_LINES // CODE_EVERY)]

problems = []
big = WS / "big.txt"
expected_lines = TOTAL_LOG_LINES + 1
if big.is_file():
    expected_lines = len(big.read_text(encoding="utf-8").splitlines())

count = WS / "count.txt"
if not count.is_file():
    problems.append("count.txt missing")
elif count.read_text(encoding="utf-8").strip() != str(expected_lines):
    problems.append(f"count.txt={count.read_text(encoding='utf-8').strip()!r} expected {expected_lines}")

magic = WS / "magic.txt"
if not magic.is_file():
    problems.append("magic.txt missing")
elif magic.read_text(encoding="utf-8").strip() != MAGIC:
    problems.append(f"magic.txt={magic.read_text(encoding='utf-8').strip()!r} expected {MAGIC}")

codes = WS / "codes.txt"
if not codes.is_file():
    problems.append("codes.txt missing")
else:
    got = [ln.strip() for ln in codes.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if got != EXPECTED_CODES:
        missing = [c for c in EXPECTED_CODES if c not in got]
        extra = [c for c in got if c not in EXPECTED_CODES]
        problems.append(
            f"codes.txt mismatch: got {len(got)} codes (expected {len(EXPECTED_CODES)}), "
            f"missing={missing[:5]}, extra={extra[:5]}, first-misordered="
            f"{next((i for i, (a, b) in enumerate(zip(got, EXPECTED_CODES)) if a != b), None)}"
        )

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
