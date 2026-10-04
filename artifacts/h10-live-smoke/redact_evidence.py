"""Redact secrets from live-smoke evidence (stdin -> stdout).

Removes, in order:
1. the exact gateway api_key value from the scratch live root config,
2. generic bearer/key shapes (sk-... tokens, Bearer headers, KEY=value lines).

Usage: python redact_evidence.py [infile] [outfile]
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

LIVE_ROOT = Path("C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root")


def _load_key() -> str:
    try:
        raw = tomllib.loads((LIVE_ROOT / "config" / "atlas.toml").read_text(encoding="utf-8"))
        return str(raw.get("models", {}).get("gateway", {}).get("api_key", "")).strip()
    except (OSError, tomllib.TOMLDecodeError):
        return ""


def redact(text: str) -> str:
    key = _load_key()
    if key:
        text = text.replace(key, "<REDACTED-KEY>")
    text = re.sub(r"sk-[A-Za-z0-9][A-Za-z0-9_-]{6,}", "<REDACTED-KEY>", text)
    # The engine banner prints a masked key fragment ("sk-a1fcd...f72c"); dots
    # defeat the class above, so mask any sk- token shape as well.
    text = re.sub(r"sk-\S{4,}", "<REDACTED-KEY>", text)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1<REDACTED-KEY>", text)
    text = re.sub(
        r"(?im)^([A-Z_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z_]*\s*[:=]\s*)\S+.*$",
        r"\1<REDACTED-KEY>",
        text,
    )
    return text


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "-"
    text = Path(source).read_text(encoding="utf-8", errors="replace") if source != "-" else sys.stdin.read()
    result = redact(text)
    if len(sys.argv) > 2:
        Path(sys.argv[2]).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
