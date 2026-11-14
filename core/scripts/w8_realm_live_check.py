"""W8/X8 realm evidence driver: two real-model automation rounds, one open
preset and one realm-scoped preset, then read each run's
``model_request_envelope.tool_names`` from the run journal.

The realm contract under test: plugin-contributed MCP tools are visible only
when the preset's ``plugins`` rows select the owning plugin (or
``plugin_allow_all``). The probe plugins each contribute one MCP server:
``0w8in`` (owned by ``w8probe``) and ``0w8out`` (owned by ``w8other``); the
``w8-scoped`` preset selects only ``w8probe``.

Usage (backend already running with ATLAS_DATA_DIR=<data-root>):
    python w8_realm_live_check.py --base http://127.0.0.1:8892 \
        --data-root D:/.../.tmp/live-data
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

IN_SERVER = "0w8in__probe_ping"
OUT_SERVER = "0w8out__other_ping"


def _http(base: str, method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
    request = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode("utf-8") if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        payload = {"_http_error": exc.code, "_body": exc.read().decode("utf-8", "replace")[:400]}
    return payload


def _journal_files(data_root: Path) -> list[Path]:
    runs = data_root / "data" / "logs" / "runs"
    files = list(runs.glob("*/*.jsonl")) if runs.is_dir() else []
    # Newest first by mtime: run ids are opaque hex, so name order is not time.
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)


def _envelope_for_conversation(data_root: Path, conversation_id: str,
                               *, settled_only: bool = False) -> tuple[dict | None, dict]:
    """Latest run journal bound to this conversation: envelope + tool records.

    ``settled_only`` waits for the run's terminal ``run_end`` record so a run
    that is still mid-turn (tools not yet dispatched) is not reported early.
    """
    for path in _journal_files(data_root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if not any(f'"session_id": "{conversation_id}"' in line for line in lines):
            continue
        records = [json.loads(line) for line in lines if line.strip()]
        if settled_only and not any(record.get("event") == "run_end" for record in records):
            return None, {}
        envelopes = [record for record in records
                     if record.get("event") == "model_request_envelope"]
        tool_calls = [
            {"event": record.get("event"), "name": record.get("name"),
             "reason": str(record.get("reason") or "")[:160]}
            for record in records
            if record.get("event") in ("tool_start", "tool_blocked")
        ]
        return (envelopes[-1] if envelopes else None), {"journal": path.name, "tool_calls": tool_calls}
    return None, {}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8892")
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--wait", type=float, default=180.0,
                        help="seconds to wait for each automation round")
    args = parser.parse_args()
    data_root = Path(args.data_root).resolve()
    failures: list[str] = []
    rounds = [
        ("open", "w8-open", "w8-open-target",
         "Call the tool named 0w8in__probe_ping with empty arguments, then call the tool "
         "named 0w8out__other_ping with empty arguments. Reply with both tools' exact outputs."),
        ("scoped", "w8-scoped", "w8-scoped-target",
         "Call the tool named 0w8in__probe_ping with empty arguments, then call the tool "
         "named 0w8out__other_ping with empty arguments. Reply with both tools' exact outputs."),
    ]
    results: dict[str, dict] = {}
    for label, preset, conversation, message in rounds:
        # A date trigger in the near future: the engine turns the schedule into
        # the DBOS workflow's delay_until, so run-now would dedup onto a
        # far-future workflow. Scheduling soon and polling is the reliable path.
        # A fresh automation id per invocation keeps the DBOS dedup slot free —
        # a leftover delayed workflow would otherwise swallow the enqueue.
        automation_id = f"w8-{label}-{uuid.uuid4().hex[:6]}"
        fire_at = datetime.now(timezone.utc).astimezone() + timedelta(seconds=10)
        record = {
            "id": automation_id,
            "name": f"W8 {label} realm probe",
            "enabled": True,
            "trigger": {"kind": "date", "at": fire_at.isoformat()},
            "payload": {
                "kind": "agent_turn", "message": message,
                "agent_preset_id": preset, "permission_preset": "free",
                "conversation_id": conversation,
            },
            "delivery": {"mode": "none"},
            "policy": {"missed_run": "skip", "delete_after_run": False},
        }
        _http(args.base, "DELETE", f"/api/automations/w8-{label}")
        created = _http(args.base, "POST", "/api/automations", record)
        created = created.get("automation") if isinstance(created.get("automation"), dict) else created
        automation_id = str(created.get("id") or "")
        if not automation_id:
            failures.append(f"[{label}] create failed: {json.dumps(created)[:300]}")
            continue
        print(f"== [{label}] automation {automation_id} preset={preset} fires_at={fire_at.isoformat()} ==")
        receipt = _http(args.base, "POST",
                        f"/api/automations/{automation_id}/run-now?wait={min(int(args.wait), 120)}",
                        timeout=min(args.wait, 120) + 30)
        print(f"    receipt={json.dumps(receipt, ensure_ascii=False)[:500]}")
        # Poll the journal until the run SETTLES (run_end) or the budget runs out;
        # tool dispatch happens after the first model response, so an early
        # envelope sighting does not mean the tool calls are journaled yet.
        envelope, tool_trace = None, {}
        deadline = time.time() + args.wait
        while time.time() < deadline:
            envelope, tool_trace = _envelope_for_conversation(
                data_root, conversation, settled_only=True)
            if envelope is not None:
                break
            time.sleep(5)
        if envelope is None:
            failures.append(f"[{label}] no model_request_envelope journal for {conversation}")
            continue
        tool_names = list(envelope.get("tool_names") or [])
        calls = tool_trace.get("tool_calls") or []
        called_in = any(item.get("name") == IN_SERVER for item in calls)
        called_out = any(item.get("name") == OUT_SERVER for item in calls)
        blocked_out = any(item.get("name") == OUT_SERVER and item.get("event") == "tool_blocked"
                          for item in calls)
        reply = str(((receipt.get("result") or {}).get("result") if isinstance(receipt.get("result"), dict) else "") or "")
        results[label] = {
            "journal": tool_trace.get("journal"),
            "tool_calls": calls,
            "called_in_probe": called_in,
            "called_out_probe": called_out,
            "out_probe_blocked": blocked_out,
            "reply_excerpt": reply[-600:],
        }
        print(f"    journal={tool_trace.get('journal')} tool_calls={json.dumps(calls, ensure_ascii=False)[:300]}")
        _http(args.base, "DELETE", f"/api/automations/{automation_id}")

    open_result = results.get("open")
    scoped_result = results.get("scoped")
    if open_result is not None:
        if not open_result["called_in_probe"]:
            failures.append("[open] in-realm probe tool was never dispatched")
        if not open_result["called_out_probe"]:
            failures.append("[open] out-of-realm probe tool was never dispatched (expected callable)")
    if scoped_result is not None:
        if not scoped_result["called_in_probe"]:
            failures.append("[scoped] in-realm probe tool was never dispatched")
        if scoped_result["called_out_probe"] and not scoped_result["out_probe_blocked"]:
            failures.append("[scoped] OUT-OF-REALM probe tool dispatched without a block")

    print("== verdict ==")
    print(json.dumps({"open": open_result, "scoped": scoped_result,
                      "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
