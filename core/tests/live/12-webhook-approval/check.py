"""Verify the file written after the channel approval round trip."""

import sys
from pathlib import Path

workspace = Path(sys.argv[1])
result = workspace / "webhook-done.txt"
assert result.is_file(), f"missing {result}"
assert result.read_text(encoding="utf-8").strip() == "CHANNEL-RECEIPT-OK"
print("CHECK-OK: webhook approval produced the requested file")
