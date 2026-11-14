"""Minimal local OTLP/HTTP probe collector for live telemetry evidence.

Accepts OTLP/HTTP ``POST /v1/traces`` protobuf bodies and records what arrived:
arrival order, request size, and every ``atlas.*`` span name recoverable from
the raw protobuf. It never parses protobuf properly — string scraping is
enough to prove which spans crossed which channel. Evidence goes to a JSONL
file and stdout.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_SPAN_NAME_RE = re.compile(rb"atlas\.[A-Za-z0-9_.\-]{2,80}")


class Handler(BaseHTTPRequestHandler):
    log_path: Path

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        names = sorted({match.group(0).decode("ascii", "replace")
                        for match in _SPAN_NAME_RE.finditer(body)})
        record = {
            "ts": time.strftime("%H:%M:%S"),
            "path": self.path,
            "bytes": len(body),
            "span_names": names,
        }
        with self.log_path.open("a", encoding="utf-8") as sink:
            sink.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(json.dumps(record, ensure_ascii=False), flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-protobuf")
        self.end_headers()
        self.wfile.write(b"")

    def do_GET(self):  # noqa: N802 - health probe
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # silence default stderr chatter
        return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int)
    parser.add_argument("log")
    args = parser.parse_args()
    Handler.log_path = Path(args.log)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"probe collector listening on {args.port}, log={args.log}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
