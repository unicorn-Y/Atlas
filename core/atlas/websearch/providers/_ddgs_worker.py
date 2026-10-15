# Ported from NousResearch/hermes-agent@c9e076b41f2163445b506b1cb79862d0dab0eecd: plugins/web/ddgs/_search_worker.py (MIT)
"""ddgs child process: one JSON request on stdin -> one envelope on stdout, then exit.

Run as ``python -m atlas.websearch.providers._ddgs_worker`` by :mod:`.ddgs`.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        from ddgs import DDGS  # type: ignore[import-not-found]
        from ddgs.exceptions import DDGSException  # type: ignore[import-not-found]
    except ImportError as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": f"ddgs not importable: {exc}"}))
        return 1
    try:
        request = json.load(sys.stdin)
        query, limit = str(request.get("query") or ""), max(1, int(request.get("limit") or 5))
        rows = []
        with DDGS(timeout=10) as client:
            for i, item in enumerate(client.text(query, max_results=limit)):
                if i >= limit:
                    break
                rows.append({"title": str(item.get("title", "")), "url": str(item.get("href") or item.get("url") or ""),
                             "description": str(item.get("body", "")), "position": i + 1})
        envelope = {"ok": True, "results": rows}
    except (DDGSException, OSError, ValueError, RuntimeError, TypeError, KeyError, AttributeError) as exc:
        envelope = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(envelope))  # ASCII-escaped: the console code page can't mangle it
    sys.stdout.flush()
    return 0 if envelope["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
