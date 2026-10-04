"""Live scenario 01 checker: the failing test now passes and the test file is untouched."""
import hashlib
import pathlib
import subprocess
import sys

WS = pathlib.Path(sys.argv[1])
PY = sys.executable

TEST_SHA_LF = "8a239afb02c6fe961e2fccb34b76c2ed8757f217a20551797d31a86f4d57594f"

test_file = WS / "test_calc.py"
calc_file = WS / "calc.py"
problems = []
if not test_file.is_file():
    problems.append("test_calc.py missing")
if not calc_file.is_file():
    problems.append("calc.py missing")
else:
    raw = test_file.read_bytes()
    digests = {
        hashlib.sha256(raw).hexdigest(),
        hashlib.sha256(raw.replace(b"\r\n", b"\n")).hexdigest(),
        hashlib.sha256(raw.replace(b"\n", b"\r\n")).hexdigest(),
    }
    if TEST_SHA_LF not in digests:
        problems.append(f"test_calc.py was modified (sha {hashlib.sha256(raw).hexdigest()})")
    proc = subprocess.run(
        [PY, "-m", "pytest", "test_calc.py", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=WS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    if proc.returncode != 0:
        problems.append(f"pytest still failing rc={proc.returncode}: {proc.stdout[-800:]} {proc.stderr[-400:]}")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
