"""Live scenario 09 checker: rewind restored step 2, retry landed, step 1 intact."""
import pathlib
import sys

WS = pathlib.Path(sys.argv[1])

problems = []
step1 = WS / "step1.txt"
step2 = WS / "step2.txt"
if not step1.is_file():
    problems.append("step1.txt missing")
elif step1.read_text(encoding="utf-8").strip() != "STEP-ONE":
    problems.append(f"step1.txt content wrong: {step1.read_text(encoding='utf-8')!r}")
if not step2.is_file():
    problems.append("step2.txt missing after retry")
elif step2.read_text(encoding="utf-8").strip() != "CORRECT-VERSION":
    problems.append(f"step2.txt content wrong: {step2.read_text(encoding='utf-8')!r}")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
