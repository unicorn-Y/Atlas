"""Run S14/S17/S20/S29 evidence against the shared isolated backend on 8874."""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import uuid
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

import websockets


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", required=True, type=Path, help="Isolated backend engine directory")
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "probe-report.md").write_text("# Live deliverable\n", encoding="utf-8")
    base = "http://127.0.0.1:8874"
    with urlopen(Request(base + "/api/conversations", data=json.dumps({"title": "W3 query source"}).encode(),
                         headers={"Content-Type": "application/json"}), timeout=20) as response:
        source = json.load(response)["id"]
    from atlas.engine.state.atlas_state import SessionDB
    with SessionDB(db_path=args.home / "state.db") as db:
        db.ensure_session(source, "api_server", cwd=str(workspace))
        db.append_message(source, "user", content="The source reference token is REFERENCE_8874.")
        seq = db.append_session_event(source, "probe/evidence", {"turn_id": "seed", "token": "QUERY_8874"})
    run_id, current = str(uuid.uuid4()), "w3-query-" + uuid.uuid4().hex[:8]
    prompt = (
        "This is an explicit tool verification request. Execute these tools in order: "
        f"session_event_search(session_id='{source}', query='QUERY_8874'); "
        f"session_event_read(session_id='{source}', seq={seq}); "
        f"session_event_trace(session_id='{source}', seq={seq}); "
        f"session_trace(session_id='{source}'); read_session(conversation_id='{source}'); "
        "present(path='probe-report.md', title='W3 live deliverable'). "
        "Do not substitute terminal or Python calls for these named tools. "
        "Then state the tokens actually read and whether the deliverable was presented."
    )
    evidence = {"source_session": source, "conversation_id": current, "run_id": run_id,
                "workspace": str(workspace), "events": []}
    async with websockets.connect("ws://127.0.0.1:8874/ws/chat", max_size=8 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "run.start", "run_id": run_id, "conversation_id": current,
                                  "workspace": str(workspace), "content": prompt}))
        deadline = asyncio.get_running_loop().time() + 180
        while asyncio.get_running_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                continue
            frame = json.loads(raw)
            event, data = frame.get("event") or frame.get("type"), frame.get("data") or {}
            evidence["events"].append(frame)
            if event in {"tool.started", "tool.completed", "run.completed", "run.failed", "run.cancelled"}:
                print(f"{event}: {data.get('name') or data.get('reason') or ''}", flush=True)
            if event == "approval.required":
                await ws.send(json.dumps({"type": "approval.response", "event_id": data.get("approval_id") or data.get("event_id"),
                                          "choice": "allow_once"}))
            if event in {"run.completed", "run.failed", "run.cancelled"}:
                evidence["terminal"] = event
                break
    with SessionDB(db_path=args.home / "state.db") as db:
        evidence["workspace_changes"] = [row for row in db.list_session_events(current) if row["event_type"] == "workspace/changes"]
    try:
        with urlopen(base + f"/api/conversations/{source}/export.zip", timeout=20) as response:
            archive = response.read()
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            evidence["zip"] = {"bytes": len(archive), "files": zipped.namelist()}
    except Exception as exc:
        evidence["zip_error"] = str(exc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"terminal": evidence.get("terminal"), "workspace_changes": len(evidence["workspace_changes"]),
                      "zip": evidence.get("zip"), "zip_error": evidence.get("zip_error"), "artifact": str(args.output)}, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
