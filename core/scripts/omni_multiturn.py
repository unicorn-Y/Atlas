"""Multi-turn context growth: does Atlas's smaller prompt stay smaller?

The single-turn benchmark shows Atlas assembling a prompt about half the size of
DSH's. That advantage only matters if it survives history growth — a per-turn
saving that scales with the conversation is worth far more than a fixed one.

This runs the *same* conversation against both harnesses and prints the prompt
size of each turn, so the growth curves can be compared directly rather than
argued about.

Usage::

    python scripts/omni_multiturn.py --turns 5 --port 8910
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from omni_bench import (  # noqa: E402 - sibling script, not a package
    ATLAS_ROOT, DSH_ROOT, PROXY, IsolatedAtlasBackend, IsolatedDSHHome,
    _atlas_ready, _atlas_usage,
    _dsh_env, _parse_dsh_stream,
    dsh_boot_ms,
)

#: One conversation, five turns. Each reply is one word so output length cannot
#: influence the prompt size — only accumulated history can.
TURNS: tuple[str, ...] = (
    "Reply with exactly the word: ONE",
    "Reply with exactly the word: TWO",
    "Reply with exactly the word: THREE",
    "Reply with exactly the word: FOUR",
    "Reply with exactly the word: FIVE",
    "Reply with exactly the word: SIX",
    "Reply with exactly the word: SEVEN",
    "Reply with exactly the word: EIGHT",
)


def run_atlas_conversation(
    turns: int, port: int, db_path: Path, workspace: Path, *, deadline_seconds: float = 45,
) -> list[dict]:
    """Drive one conversation and record prompt tokens per turn."""
    import websockets

    conversation = f"multi-{int(time.monotonic() * 1000)}"
    rows: list[dict] = []

    async def _turn(index: int, prompt: str) -> dict:
        absolute_deadline = time.monotonic() + deadline_seconds
        run_id = f"{conversation}-{index}"
        reply: list[str] = []
        async with websockets.connect(f"ws://127.0.0.1:{port}/ws/chat",
                                      max_size=8 * 1024 * 1024) as ws:
            await ws.send(json.dumps({
                "type": "run.start", "run_id": run_id,
                "conversation_id": conversation, "content": prompt,
                "workspace": str(workspace),
            }))
            terminal = None
            event_counts: Counter[str] = Counter()
            phase_counts: Counter[str] = Counter()
            first_waiting: str | None = None
            protocol_error: str | None = None
            while True:
                remaining = absolute_deadline - time.monotonic()
                if remaining <= 0:
                    terminal = "absolute_deadline_exceeded"
                    break
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(10, remaining))
                except asyncio.TimeoutError:
                    if time.monotonic() >= absolute_deadline:
                        terminal = "absolute_deadline_exceeded"
                        break
                    continue
                event = json.loads(raw)
                kind = event.get("event") or event.get("type")
                data = event.get("data") or {}
                event_counts[str(kind or "unknown")] += 1
                phase = data.get("phase") or event.get("phase")
                if phase:
                    phase_counts[str(phase)] += 1
                if kind in {"rules.trust_required", "approval.required", "input.required"}:
                    first_waiting = first_waiting or str(kind)
                    terminal = f"waiting:{kind}"
                    break
                if kind in {"protocol.error", "error"}:
                    protocol_error = str(data.get("code") or data.get("type") or kind)
                    terminal = "protocol_error"
                    break
                if kind == "run.status" and str(data.get("status") or "").casefold() in {
                    "waiting", "waiting_for_approval", "waiting_for_input", "waiting_for_trust",
                }:
                    first_waiting = first_waiting or f"run.status:{data.get('status')}"
                    terminal = first_waiting
                    break
                if kind == "message.delta":
                    reply.append(str(data.get("content") or ""))
                if kind in {"run.completed", "run.failed", "run.cancelled"}:
                    terminal = kind
                    if kind == "run.failed":
                        protocol_error = str(data.get("category") or "run_failed")
                    break
        ledger = _atlas_usage(run_id, db_path)
        expected = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT")[index]
        final_text = "".join(reply).strip()
        ok = terminal == "run.completed" and " ".join(final_text.split()) == expected
        return {
            "turn": index + 1,
            "ok": ok,
            "final": final_text,
            "prompt_tokens": ledger.get("input_tokens") if ledger else None,
            "cached": ledger.get("cached_input_tokens") if ledger else None,
            "usage_complete": ledger is not None,
            "session_id": conversation,
            "session_continuity": True,
            "event_counts": dict(event_counts),
            "phase_counts": dict(phase_counts),
            "first_waiting_type": first_waiting,
            "protocol_error_type": protocol_error,
            "terminal": terminal,
        }

    for index, prompt in enumerate(TURNS[:turns]):
        row = asyncio.run(_turn(index, prompt))
        rows.append(row)
        if not row.get("ok"):
            break
    return rows


def run_dsh_conversation(turns: int) -> list[dict]:
    """Same conversation through DSH, resuming one session across turns."""
    import subprocess

    session_id: str | None = None
    rows: list[dict] = []
    for index, prompt in enumerate(TURNS[:turns]):
        argv = ["pnpm", "dsh", "headless", "--json"]
        if session_id is not None:
            argv += ["--session-id", session_id]
        argv.append(prompt)
        try:
            proc = subprocess.run(
                argv, cwd=str(DSH_ROOT),
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=240, env=_dsh_env(), shell=True,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            rows.append({"turn": index + 1, "ok": False, "error": str(exc)[:200]})
            continue
        parsed = _parse_dsh_stream(proc.stdout or "")
        returned_ids = set(parsed["session_ids"])
        adopted = next(iter(returned_ids)) if len(returned_ids) == 1 else None
        if index == 0:
            if not adopted:
                rows.append({
                    "turn": 1, "ok": False,
                    "error": "DSH did not report a sessionId, so the conversation "
                             "cannot be continued; later turns would be independent "
                             "sessions and the growth curve would be meaningless",
                })
                return rows
            session_id = adopted
        continuity_ok = adopted == session_id
        expected = ("ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT")[index]
        final_text = str(parsed.get("final_text") or "").strip()
        answer_ok = " ".join(final_text.split()) == expected
        terminal_ok = parsed.get("terminal") == "completed" and proc.returncode == 0
        usage = parsed["usage"]
        prompt_tokens = None
        if parsed["usage_complete"]:
            fields = (usage.get("inputTokens"), usage.get("cacheReadTokens"),
                      usage.get("cacheWriteTokens"))
            if all(isinstance(value, int) for value in fields):
                prompt_tokens = sum(fields)
        rows.append({
            "turn": index + 1,
            "ok": terminal_ok and answer_ok and continuity_ok,
            "final": final_text,
            "prompt_tokens": prompt_tokens,
            "cached": usage.get("cacheReadTokens"),
            "cache_write": usage.get("cacheWriteTokens"),
            "usage_complete": parsed["usage_complete"],
            "session_id": adopted,
            "session_continuity": continuity_ok,
            "error": (parsed.get("terminal_error") or
                      (None if answer_ok and continuity_ok else "final answer/session validation failed")),
        })
        if not rows[-1]["ok"]:
            break
    return rows


def _atlas_route_diagnostic(port: int) -> dict[str, object]:
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/__bench/model-route", timeout=4) as response:
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, dict):
            return {"available": False, "reason": "invalid_diagnostic_response"}
        return value
    except Exception as exc:  # noqa: BLE001 - report only the exception class
        return {"available": False, "reason": type(exc).__name__}


def report(
    atlas: list[dict], dsh: list[dict], boot_ms: int | None, out: Path,
    route_diagnostic: dict[str, object] | None = None,
) -> None:
    lines = [
        "# Multi-turn context growth",
        "",
        "Same eight-turn conversation, one word per reply, run against both",
        "harnesses. Only accumulated history can change the prompt size.",
        "",
        "| Turn | Atlas prompt | DSH prompt | Atlas / DSH |",
        "|---:|---:|---:|---:|",
    ]
    for index in range(max(len(atlas), len(dsh))):
        a = atlas[index] if index < len(atlas) else {}
        d = dsh[index] if index < len(dsh) else {}
        ap, dp = a.get("prompt_tokens"), d.get("prompt_tokens")
        ratio = f"{ap/dp:.2f}×" if isinstance(ap, int) and isinstance(dp, int) and dp else "—"
        lines.append(
            f"| {index + 1} | {ap if ap is not None else 'NOT-MEASURED'} "
            f"| {dp if dp is not None else 'NOT-MEASURED'} | {ratio} |"
        )

    lines += ["", "## Run evidence", ""]
    if route_diagnostic is not None:
        lines.append(f"- Atlas isolated route (secrets scrubbed): `{route_diagnostic}`")
    for name, rows in (("Atlas", atlas), ("DSH", dsh)):
        for row in rows:
            lines.append(
                f"- {name} turn {row['turn']}: ok={row['ok']}; "
                f"final={row.get('final')!r}; session={row.get('session_id') or 'UNKNOWN'}; "
                f"usage={'complete' if row.get('usage_complete') else 'partial/unknown'}; "
                f"session_continuity={row.get('session_continuity', 'same Atlas conversation id')}"
            )
            if name == "Atlas":
                lines.append(
                    f"  - terminal={row.get('terminal')}; events={row.get('event_counts', {})}; "
                    f"phases={row.get('phase_counts', {})}; "
                    f"first_waiting_type={row.get('first_waiting_type') or 'none'}; "
                    f"failure_category={row.get('protocol_error_type') or 'none'}"
                )

    a_first = next((r["prompt_tokens"] for r in atlas if r.get("prompt_tokens")), None)
    a_last = next((r["prompt_tokens"] for r in reversed(atlas) if r.get("prompt_tokens")), None)
    d_first = next((r["prompt_tokens"] for r in dsh if r.get("prompt_tokens")), None)
    d_last = next((r["prompt_tokens"] for r in reversed(dsh) if r.get("prompt_tokens")), None)

    lines += ["", "## Growth", ""]
    if a_first and a_last:
        lines.append(f"- Atlas: {a_first:,} → {a_last:,} tokens "
                     f"(+{a_last - a_first:,} over {len(atlas) - 1} turns)")
    if d_first and d_last:
        lines.append(f"- DSH: {d_first:,} → {d_last:,} tokens "
                     f"(+{d_last - d_first:,} over {len(dsh) - 1} turns)")
    if a_last and d_last:
        lines.append(f"- At the last turn Atlas carries **{d_last - a_last:,} fewer** prompt tokens.")
    if boot_ms:
        lines.append(f"- DSH boot baseline for reference: {boot_ms:,} ms/turn")

    lines += [
        "",
        "A per-turn prompt saving that holds as history grows is worth more than",
        "the fixed single-turn saving, because it compounds over a long session.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=8)
    parser.add_argument("--port", type=int, default=8910)
    parser.add_argument("--only", choices=("atlas", "dsh"), default=None)
    parser.add_argument("--out", default=str(ATLAS_ROOT / "tasks" / "dsh-parity" / "MULTITURN.md"))
    args = parser.parse_args()

    atlas: list[dict] = []
    dsh: list[dict] = []
    boot_ms: int | None = None
    backend: IsolatedAtlasBackend | None = None
    route_diagnostic: dict[str, object] | None = None
    try:
        if args.only in (None, "atlas"):
            backend = IsolatedAtlasBackend(args.port, isolate_hooks=True)
            if not _atlas_ready(args.port):
                print(f"Atlas backend not answering on :{args.port}", file=sys.stderr)
                return 2
            workspace = backend.data_dir / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            route_diagnostic = _atlas_route_diagnostic(args.port)
            print(f"[atlas] isolated_route={route_diagnostic}")
            atlas = run_atlas_conversation(args.turns, args.port, backend.db_path, workspace)
            for row in atlas:
                print(
                    f"[atlas] turn {row['turn']}: tokens={row.get('prompt_tokens')} "
                    f"ok={row['ok']} terminal={row.get('terminal')} "
                    f"events={row.get('event_counts')} phases={row.get('phase_counts')} "
                    f"first_waiting={row.get('first_waiting_type')} "
                    f"protocol_error={row.get('protocol_error_type')}"
                )
        if args.only in (None, "dsh"):
            dsh_home = IsolatedDSHHome()
            try:
                dsh = run_dsh_conversation(args.turns)
                for row in dsh:
                    print(f"[dsh]   turn {row['turn']}: {row.get('prompt_tokens')} tokens ok={row['ok']}")
                boot_ms = dsh_boot_ms()
            finally:
                dsh_home.close()
        report(atlas, dsh, boot_ms, Path(args.out), route_diagnostic)
    finally:
        if backend is not None:
            backend.close()
            lifecycle = (
                f"[atlas] child exit={backend.exit_code}; "
                f"forced_termination={backend.forced_termination}; "
                f"graceful_lifespan={backend.graceful_exit}; "
                f"private_log_summary={backend.log_summary!r}"
            )
            print(lifecycle)
            out_path = Path(args.out)
            with out_path.open("a", encoding="utf-8") as stream:
                stream.write("\n## Isolated backend lifecycle\n\n- " + lifecycle + "\n")
    return 1 if any(not row.get("ok") for row in atlas + dsh) else 0


if __name__ == "__main__":
    raise SystemExit(main())
