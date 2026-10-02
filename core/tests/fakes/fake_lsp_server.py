"""Fake LSP language server for Atlas tests (subagent E, C6A LSP wave).

Standalone asyncio stdio JSON-RPC 2.0 server speaking the ``Content-Length``
framing from ``atlas.lsp.protocol``.  Deterministic, cross-platform diagnostics
so the client/service suites never need a real pyright/tsserver:

- text containing ``LSP_BUG`` → one error (``code="T999"``, ``source="fakeserver"``)
  on the first marked line (0-based), range characters 4..11;
- otherwise an empty diagnostic list (i.e. fixing the marker clears the error);
- ``--seed`` → the first ``publishDiagnostics`` is a stale baseline push
  (one history warning, no ``version``) sent immediately, mimicking the TS
  first-push semantics; it must never count as fresh in the client.

Usage::

    python fake_lsp_server.py --server-id fake --state-file state.json [--delay-ms 150] [--seed]

Lifecycle: ``initialize`` (writes/updates the state file with ``initialized:
true``) → ``initialized`` ignored → ``textDocument/didOpen``/``didChange``
record the text, then after ``--delay-ms`` a versioned ``publishDiagnostics``
push goes out → ``textDocument/diagnostic`` answers ``{"kind": "full",
"items": []}`` only after pending pushes have landed (it never competes with
push) → ``shutdown`` (state file gains ``shutdown: true``) → ``exit`` (process
exit code 0).  ``workspace/
didChangeWatchedFiles``, ``$/...`` and ``window/...`` notifications are
silently ignored; unknown *requests* get ``-32601``.

stdin/stdout use raw binary frames (``sys.stdin.buffer`` / ``sys.stdout.buffer``);
on Windows the process is spawned directly (no shell wrapper).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
from pathlib import Path

# The fake lives at <core>/tests/fakes/fake_lsp_server.py and is usually spawned
# with a different cwd (the workspace root); make ``atlas`` importable anyway.
_CORE = Path(__file__).resolve().parents[2]
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

from atlas.lsp.protocol import (  # noqa: E402
    ERROR_METHOD_NOT_FOUND,
    classify_message,
    encode_message,
    make_error_response,
    make_notification,
    make_response,
    read_message,
)

MARKER = "LSP_BUG"
STREAM_LIMIT = 16 * 1024 * 1024


def _capabilities() -> dict:
    return {
        "capabilities": {
            "textDocumentSync": {"change": 2},
            "diagnosticProvider": {
                "interDocumentDependencies": False,
                "workspaceDiagnostics": False,
            },
        }
    }


def _diagnose(text: str) -> list[dict]:
    """Deterministic diagnostics for ``text`` (see module docstring)."""
    for idx, line in enumerate(text.splitlines()):
        if MARKER in line:
            return [
                {
                    "range": {
                        "start": {"line": idx, "character": 4},
                        "end": {"line": idx, "character": 11},
                    },
                    "severity": 1,
                    "code": "T999",
                    "source": "fakeserver",
                    "message": f"Fake type error: LSP_BUG on line {idx + 1}",
                }
            ]
    return []


def _seed_warning() -> dict:
    """A stale "history" warning for the ``--seed`` baseline push."""
    return {
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 7},
        },
        "severity": 2,
        "code": "H100",
        "source": "fakeserver",
        "message": "Stale history warning from previous session",
    }


def _line_start_offsets(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    return starts


def _pos_to_offset(text: str, starts: list[int], pos: dict) -> int:
    line = int(pos.get("line", 0))
    character = int(pos.get("character", 0))
    if line >= len(starts):
        return len(text)
    return min(starts[line] + character, len(text))


def _apply_edit(text: str, change: dict) -> str:
    """Apply one incremental (ranged) or full-content change to ``text``."""
    new_text = change.get("text", "")
    rng = change.get("range")
    if not rng:
        return new_text
    starts = _line_start_offsets(text)
    start = _pos_to_offset(text, starts, rng.get("start") or {})
    end = _pos_to_offset(text, starts, rng.get("end") or {})
    return text[:start] + new_text + text[end:]


class FakeServer:
    def __init__(self, args: argparse.Namespace) -> None:
        self.server_id = args.server_id
        self.state_file = Path(args.state_file) if args.state_file else None
        self.delay = max(0, args.delay_ms) / 1000.0
        self.seed = args.seed
        self.state: dict = {"server_id": args.server_id, "pid": os.getpid(), "initialized": False}
        self.texts: dict[str, str] = {}
        self.versions: dict[str, int] = {}
        self._seed_push_done = False
        self._tasks: set[asyncio.Task] = set()  # strong refs: GC'd tasks would silently drop pushes

    # ---- state file ----

    def _flush_state(self) -> None:
        if self.state_file is None:
            return
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state), encoding="utf-8")
        except OSError:
            pass  # a test fixture must never die over its state file

    # ---- wire plumbing ----

    def _write(self, msg: dict) -> None:
        sys.stdout.buffer.write(encode_message(msg))
        sys.stdout.buffer.flush()

    async def send(self, msg: dict) -> None:
        self._write(msg)

    async def _push_after_delay(self, uri: str) -> None:
        await asyncio.sleep(self.delay)
        params: dict = {"uri": uri, "diagnostics": _diagnose(self.texts.get(uri, ""))}
        version = self.versions.get(uri)
        if version is not None:
            params["version"] = version
        await self.send(make_notification("textDocument/publishDiagnostics", params))

    def _on_document_touched(self, uri: str) -> None:
        if self.seed and not self._seed_push_done:
            # First publishDiagnostics is the stale baseline: sent immediately,
            # carrying a history warning and NO version (never fresh in the client).
            self._seed_push_done = True
            self._write(
                make_notification(
                    "textDocument/publishDiagnostics",
                    {"uri": uri, "diagnostics": [_seed_warning()]},
                )
            )
        task = asyncio.get_running_loop().create_task(self._push_after_delay(uri))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ---- dispatch ----

    async def handle(self, msg: dict) -> bool:
        """Process one inbound envelope; ``False`` means the server should exit."""
        kind, key = classify_message(msg)
        if kind == "request":
            await self._handle_request(key, msg.get("method", ""), msg.get("params"))
        elif kind == "notification":
            return await self._handle_notification(msg.get("method", ""), msg.get("params"))
        # responses and invalid envelopes are dropped
        return True

    async def _handle_request(self, req_id, method: str, params) -> None:
        if method == "initialize":
            self.state["initialized"] = True
            self._flush_state()
            await self.send(make_response(req_id, _capabilities()))
        elif method == "shutdown":
            self.state["shutdown"] = True
            self._flush_state()
            await self.send(make_response(req_id, None))
        elif method == "textDocument/diagnostic":
            # Pull never competes with push: defer the answer until every
            # in-flight delayed push has landed, so the client's pull store can
            # never read as a fresh "clean" verdict ahead of the real push.
            while self._tasks:
                await asyncio.wait(set(self._tasks))
            await self.send(make_response(req_id, {"kind": "full", "items": []}))
        else:
            await self.send(
                make_error_response(req_id, ERROR_METHOD_NOT_FOUND, f"method not found: {method}")
            )

    async def _handle_notification(self, method: str, params) -> bool:
        if method == "textDocument/didOpen":
            td = (params or {}).get("textDocument") or {}
            uri = td.get("uri")
            if uri:
                self.texts[uri] = str(td.get("text", ""))
                self.versions[uri] = int(td.get("version", 0))
                self._on_document_touched(uri)
        elif method == "textDocument/didChange":
            td = (params or {}).get("textDocument") or {}
            uri = td.get("uri")
            if uri:
                text = self.texts.get(uri, "")
                for change in (params or {}).get("contentChanges") or []:
                    if isinstance(change, dict):
                        text = _apply_edit(text, change)
                self.texts[uri] = text
                if "version" in td:
                    self.versions[uri] = int(td["version"])
                self._on_document_touched(uri)
        elif method == "exit":
            return False
        # initialized / workspace/didChangeWatchedFiles / $/... / window/... : silently ignored
        return True


async def _pump_stdin(reader: asyncio.StreamReader) -> None:
    """Feed the asyncio reader from a blocking thread: Windows Proactor loops do
    not reliably support ``connect_read_pipe`` on anonymous stdin pipes."""
    loop = asyncio.get_running_loop()
    stdin = sys.stdin.buffer

    def _read_loop() -> None:
        while True:
            try:
                chunk = stdin.read1(STREAM_LIMIT)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                loop.call_soon_threadsafe(reader.feed_eof)
                return
            loop.call_soon_threadsafe(reader.feed_data, chunk)

    threading.Thread(target=_read_loop, name="fake-lsp-stdin", daemon=True).start()


async def _serve(server: FakeServer) -> int:
    reader = asyncio.StreamReader(limit=STREAM_LIMIT)
    await _pump_stdin(reader)
    while True:
        msg = await read_message(reader)
        if msg is None:  # clean EOF: parent closed the pipe
            return 0
        if not await server.handle(msg):
            return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fake LSP language server for Atlas tests")
    parser.add_argument("--server-id", default="fake")
    parser.add_argument("--state-file", default="")
    parser.add_argument("--delay-ms", type=int, default=150)
    parser.add_argument("--seed", action="store_true", help="first publishDiagnostics is a stale, versionless baseline push")
    args = parser.parse_args(argv)

    server = FakeServer(args)
    print(f"fake-lsp-server ready ({server.server_id}) pid={os.getpid()}", file=sys.stderr, flush=True)
    code = asyncio.run(_serve(server))
    try:
        sys.stdout.buffer.flush()
        sys.stderr.flush()
    except OSError:
        pass
    # The stdin pump thread is still blocked in read1() when ``exit`` arrives;
    # walking interpreter finalization with it crashes with 0xC0000005 on
    # Windows.  Every buffer is flushed above, so leave hard.
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())
