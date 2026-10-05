"""Live scenario 08 checker: greet.py exists, runs, and greets in Chinese."""
import os
import pathlib
import subprocess
import sys

WS = pathlib.Path(sys.argv[1])

# Checker diagnostics can include text that the active Windows code page cannot
# encode (for example U+FFFD after decoding malformed child output).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="backslashreplace")

problems = []
greet = WS / "greet.py"
if not greet.is_file():
    problems.append("greet.py missing")
else:
    proc = subprocess.run(
        [sys.executable, "greet.py"],
        cwd=WS, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
    )
    out = (proc.stdout or "").strip()
    if proc.returncode != 0 or "你好，Atlas！" not in out:
        problems.append(f"python greet.py rc={proc.returncode} output={out!r} stderr={proc.stderr[-300:]!r}")

if problems:
    print("CHECK-FAIL")
    for item in problems:
        print("-", item)
    sys.exit(1)
print("CHECK-OK")
