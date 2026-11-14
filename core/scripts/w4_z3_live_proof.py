"""Live-model evidence orchestrator for WAVE4-Z3 session persistence rows.

Drives real turns through a running Atlas backend (WebSocket), polls the
cross-process turn lease from a SEPARATE process while each turn runs, then
inspects the durable store and HTTP projections. Every observation is written
to an evidence JSON so the RESULT file can quote it verbatim.

Phases (backend must be running on --port unless stated otherwise):
  phase1  seed + baseline turn + big-tool-output turn + S5/S12/S15/S16/S17/S18 checks
  resume  run AFTER a backend restart: same conversation, one more turn, then
          prove the masked tool result stays masked across restart (S9) and
          the projection cache serves the rebuilt history (S12)
  s14     seed a source session and make the model call the session-query
          five-piece tool surface (S14)

Usage:
  python scripts/w4_z3_live_proof.py <phase> --home <engine_dir> --workspace <dir> \
      --state <state.json> --output <evidence.json> [--port 8883]
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import websockets

SCRIPT_DIR = Path(__file__).resolve().parent


def http_json(port: int, path: str, timeout: float = 30.0):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        return response.status, json.loads(response.read().decode("utf-8", "replace"))


def http_bytes(port: int, path: str, timeout: float = 30.0):
    with urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        return response.status, response.read(), dict(response.headers)


async def run_turn(port: int, conversation_id: str, workspace: Path, content: str,
                   *, events_out: list | None = None, deadline_s: float = 240.0,
                   on_frame=None) -> dict:
    run_id = f"w4z3-{int(time.time()*1000)}"
    url = f"ws://127.0.0.1:{port}/ws/chat"
    text_parts: list[str] = []
    terminal = None
    async with websockets.connect(url, max_size=32 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "run.start", "run_id": run_id,
                                  "conversation_id": conversation_id,
                                  "workspace": str(workspace), "content": content}))
        loop_deadline = asyncio.get_running_loop().time() + deadline_s
        while asyncio.get_running_loop().time() < loop_deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if events_out is not None:
                events_out.append(frame)
            if on_frame is not None:
                on_frame(frame)
            event = frame.get("event") or frame.get("type")
            data = frame.get("data") or {}
            if event in {"approval.required", "run.plan.proposed"}:
                await ws.send(json.dumps({
                    "type": "approval.response",
                    "event_id": data.get("approval_id") or data.get("event_id"),
                    "choice": "allow_once"}))
            elif event == "input.required":
                await ws.send(json.dumps({
                    "type": "input.response",
                    "event_id": data.get("approval_id") or data.get("event_id") or data.get("input_id"),
                    "text": "continue with the requested tools"}))
            elif event == "message.delta":
                text_parts.append(str(data.get("content") or ""))
            elif event in {"run.completed", "run.failed", "run.cancelled"}:
                terminal = event
                break
    return {"run_id": run_id, "terminal": terminal, "reply": "".join(text_parts)}


def lease_probe(home: Path, conversation_id: str, tag: str, out_dir: Path) -> dict:
    """Run the separate-process probe once and return its parsed report."""
    out_path = out_dir / f"lease-probe-{tag}.json"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "w4_z3_lease_probe.py"),
         str(home), conversation_id, tag, str(out_path)],
        capture_output=True, text=True, timeout=120, cwd=str(SCRIPT_DIR.parent))
    try:
        return json.loads(out_path.read_text(encoding="utf-8"))
    except Exception:
        return {"error": proc.stdout[-400:] + proc.stderr[-400:]}


async def turn_with_lease_probes(port: int, conversation_id: str, workspace: Path,
                                 content: str, home: Path, out_dir: Path,
                                 tag: str, events: list) -> dict:
    """Run one turn while a separate process polls the turn lease."""
    probes: list[dict] = []
    counter = {"n": 0}

    def on_frame(frame):
        event = frame.get("event") or frame.get("type")
        if counter["n"] < 40 and event in {
            "run.started", "run.phase", "message.delta", "tool.started",
        }:
            # Fire a probe early and then roughly every few frames; cheap.
            counter["n"] += 1
            if counter["n"] % 6 == 1:
                try:
                    probes.append(lease_probe(home, conversation_id, f"{tag}-{counter['n']}", out_dir))
                except Exception as exc:  # noqa: BLE001
                    probes.append({"error": str(exc)})

    result = await run_turn(port, conversation_id, workspace, content,
                            events_out=events, on_frame=on_frame)
    try:
        probes.append(lease_probe(home, conversation_id, f"{tag}-final", out_dir))
    except Exception as exc:  # noqa: BLE001
        probes.append({"error": str(exc)})
    result["lease_probes"] = probes
    return result


def db_checks_phase1(home: Path, conversation_id: str) -> dict:
    from atlas.engine.state.atlas_state import SessionDB

    checks: dict = {}
    with SessionDB(db_path=home / "state.db") as db:
        rows = [dict(row) for row in db._read_rows(
            "SELECT session_id, key, ver, seq, LENGTH(val) AS bytes FROM session_projcache "
            "WHERE session_id = ?", (conversation_id,))]
        checks["projcache_rows"] = rows
        checks["turn_leases_after_turns"] = [dict(row) for row in db._read_rows(
            "SELECT conversation_id, holder, expires_at FROM session_turn_leases "
            "WHERE conversation_id = ?", (conversation_id,))]
        events = db.list_session_events(conversation_id, after_seq=0, limit=200)
        checks["turn_events"] = [event["event_type"] for event in events]
        checks["timeline"] = db.get_session_timeline(conversation_id, limit=50)
        # Masked tool result rows (S18/S9 persistence shape)
        masked = db._read_rows(
            "SELECT role, LENGTH(content) AS len, display_metadata FROM messages "
            "WHERE session_id = ? AND display_metadata LIKE '%output_ref%' "
            "ORDER BY id DESC LIMIT 3", (conversation_id,))
        checks["masked_tool_rows"] = [dict(row) for row in masked]
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("phase1", "resume", "s14"))
    parser.add_argument("--port", type=int, default=8883)
    parser.add_argument("--home", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.workspace.mkdir(parents=True, exist_ok=True)
    args.home.mkdir(parents=True, exist_ok=True)
    out_dir = args.output.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    state = json.loads(args.state.read_text(encoding="utf-8")) if args.state.exists() else {}
    evidence: dict = {"phase": args.phase, "port": args.port, "home": str(args.home),
                      "workspace": str(args.workspace)}

    if args.phase == "phase1":
        # Seed a marker file the big-output turn reads through a real tool.
        marker = "Y" * 45000
        (args.workspace / "big_output.txt").write_text(marker, encoding="utf-8")
        conv_a = state.get("conversation_id") or f"w4z3-live-{time.time_ns() % 100000}"
        state["conversation_id"] = conv_a
        state.setdefault("conversation_id", conv_a)

        # --- Turn A: baseline, with cross-process lease polling (S5) ---
        events_a: list = []
        result_a = asyncio.run(turn_with_lease_probes(
            args.port, conv_a, args.workspace, "Reply with exactly the word: OK",
            args.home, out_dir, "turnA", events_a))
        evidence["turnA"] = result_a
        held_by_run = [p for p in result_a["lease_probes"]
                       if not p.get("acquired") and (p.get("existing_holder") or {}).get("holder", "").find(":run=") >= 0]
        evidence["S5_lease_held_during_turn"] = {
            "probe_count": len(result_a["lease_probes"]),
            "probes_refused_while_run_holds": len(held_by_run),
            "sample_holder": (held_by_run[0].get("existing_holder") if held_by_run else None),
            "released_after": result_a["lease_probes"][-1].get("acquired") is True
                              or not result_a["lease_probes"][-1].get("existing_holder"),
        }

        # --- HTTP projections after a real turn (S15/S16/S17) ---
        status, stats = http_json(args.port, f"/api/conversations/{conv_a}/stats")
        evidence["S15_stats"] = {"status": status, "sessionStats": stats.get("sessionStats"),
                                 "message_count": stats.get("message_count")}
        status, blob, headers = http_bytes(args.port, f"/api/conversations/{conv_a}/export.zip")
        archive_info: dict = {"status": status, "bytes": len(blob),
                              "content_type": headers.get("Content-Type")}
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as zipped:
                names = zipped.namelist()
                archive_info["files"] = names
                manifest = json.loads(zipped.read("manifest.json").decode("utf-8"))
                archive_info["root_session_id"] = manifest.get("root_session_id")
                archive_info["sessions"] = len(manifest.get("sessions") or [])
                archive_info["export_format"] = manifest.get("export_format")
        except Exception as exc:  # noqa: BLE001
            archive_info["error"] = str(exc)
        evidence["S17_export_zip"] = archive_info
        status, document = http_json(args.port, f"/api/conversations/{conv_a}/export")
        evidence["S17_export_json"] = {"status": status, "format": document.get("export_format"),
                                       "messages": len(document.get("messages") or [])}

        # --- Turn B: oversized tool output through a real tool (S18/S9) ---
        events_b: list = []
        prompt_b = (
            "Use the local_exec tool to print the file big_output.txt in the current "
            "workspace (for example: type big_output.txt on Windows, or cat big_output.txt). "
            "Do not summarize it. After the tool returns, reply with exactly: MASKED_DONE"
        )
        result_b = asyncio.run(turn_with_lease_probes(
            args.port, conv_a, args.workspace, prompt_b, args.home, out_dir, "turnB", events_b))
        evidence["turnB"] = {k: result_b[k] for k in ("run_id", "terminal", "reply")}
        evidence["turnB_tool_names"] = [ (f.get("data") or {}).get("name")
                                         for f in events_b if (f.get("event") or f.get("type")) == "tool.started" ]
        evidence["turnB_tool_events"] = [
            {"event": (f.get("event") or f.get("type")),
             "name": (f.get("data") or {}).get("name"),
             "output_ref": (f.get("data") or {}).get("output_ref"),
             "clipped": {k: (f.get("data") or {}).get(k) for k in ("original_bytes", "clipped_bytes")}
             if (f.get("data") or {}).get("original_bytes") else None}
            for f in events_b if "clipped" in str((f.get("event") or f.get("type"))) or "microcompact" in str((f.get("event") or f.get("type")))
        ]

        # --- Durable-store checks (S12/S16/S18/S9-persisted) ---
        checks = db_checks_phase1(args.home, conv_a)
        evidence["db_checks"] = checks
        # spill inventory under the run logs of this workspace (S18)
        spills = sorted(p for p in args.home.rglob("*.txt") if p.stat().st_size > 20000)
        evidence["S18_spill_files"] = [
            {"path": str(p), "bytes": p.stat().st_size} for p in spills[:5]]

    elif args.phase == "resume":
        conv_a = state["conversation_id"]
        events_c: list = []
        result_c = asyncio.run(run_turn(
            args.port, conv_a, args.workspace,
            "Reply with exactly the word: RESUMED", events_out=events_c))
        evidence["turnC"] = result_c
        from atlas.engine.state.atlas_state import SessionDB
        with SessionDB(db_path=args.home / "state.db") as db:
            payload = db.export_session(conv_a, include_compacted=False)
            rows = [dict(row) for row in db._read_rows(
                "SELECT session_id, key, ver, seq, LENGTH(val) AS bytes FROM session_projcache "
                "WHERE session_id = ?", (conv_a,))]
        history_texts = [str(message.get("content") or "") for message in (payload or {}).get("messages", [])]
        marker_full = "Y" * 45000
        evidence["S9_after_restart"] = {
            "turnC_terminal": result_c["terminal"],
            "model_history_roles": [message.get("role") for message in (payload or {}).get("messages", [])],
            "full_marker_in_history": marker_full in "\n".join(history_texts),
            "masked_rows": [
                {"len": len(text), "has_output_ref_hint": "full output saved at" in text
                 or "output_ref" in text}
                for text in history_texts if len(text) > 4000],
            "projcache_rows_after_restart": rows,
        }

    elif args.phase == "s14":
        from atlas.engine.state.atlas_state import SessionDB
        source = state.get("s14_source") or f"w4z3-src-{time.time_ns() % 100000}"
        state["s14_source"] = source
        with SessionDB(db_path=args.home / "state.db") as db:
            db.ensure_session(source, "api_server", cwd=str(args.workspace.resolve()))
            db.append_message(source, "user", content="The source reference token is QUERY_8883.")
            seq = db.append_session_event(source, "probe/evidence", {"turn_id": "seed", "token": "QUERY_8883"})
        evidence["s14_source"] = {"session_id": source, "seq": seq}
        conv_d = state.get("s14_conv") or f"w4z3-q-{time.time_ns() % 100000}"
        state["s14_conv"] = conv_d
        events_d: list = []
        prompt = (
            "This is an explicit tool-verification request. Execute these tools in order: "
            f"session_event_search(session_id='{source}', query='QUERY_8883'); "
            f"session_event_read(session_id='{source}', seq={seq}); "
            f"session_trace(session_id='{source}'). "
            "Do not substitute terminal or Python calls for these named tools. "
            "Then reply with the token you actually read."
        )
        result_d = await_run_sync(args.port, conv_d, args.workspace, prompt, events_d)
        evidence["turnD"] = {k: result_d[k] for k in ("run_id", "terminal", "reply")}
        evidence["turnD_tool_calls"] = [
            {"event": (f.get("event") or f.get("type")), "name": (f.get("data") or {}).get("name")}
            for f in events_d if (f.get("event") or f.get("type")) in {"tool.started", "tool.completed"}]

    args.state.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in evidence if k in
                      ("S5_lease_held_during_turn", "S15_stats", "S17_export_zip",
                       "S17_export_json", "turnB_tool_names", "turnB_tool_events",
                       "S18_spill_files", "S9_after_restart", "turnD", "turnD_tool_calls",
                       "s14_source")}, ensure_ascii=False, indent=2)[:6000])
    print("EVIDENCE_WRITTEN", args.output, flush=True)
    return 0


def await_run_sync(port, conv, workspace, prompt, events):
    return asyncio.run(run_turn(port, conv, workspace, prompt, events_out=events))


if __name__ == "__main__":
    raise SystemExit(main())
