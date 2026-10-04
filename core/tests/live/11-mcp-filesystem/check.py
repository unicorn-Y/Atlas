"""Live scenario 11 checker: stdin (the run's final message) contains the vault magic number."""
import sys

MAGIC = "9137"

answer = sys.stdin.read()
if MAGIC not in answer:
    print(f"CHECK-FAIL: answer missing magic {MAGIC}: {answer[-400:]!r}")
    sys.exit(1)
print("CHECK-OK")
