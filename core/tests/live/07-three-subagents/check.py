"""Live scenario 07 checker: three independent subtask artifacts, exact content."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])

EXPECT = {"a": "ALPHA", "b": "BETA", "c": "GAMMA"}
problems = []
for name, content in EXPECT.items():
    target = WS / name / f"{name}.txt"
    if not target.is_file():
        problems.append(f"{name}/{name}.txt missing")
    elif target.read_text(encoding="utf-8").strip() != content:
        problems.append(f"{name}/{name}.txt content wrong: {target.read_text(encoding='utf-8')!r}")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
