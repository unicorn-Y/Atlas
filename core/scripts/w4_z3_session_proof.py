"""Engine-level evidence for WAVE4-Z3 session persistence rows against a real SessionDB.

Covers, with real files and real transactions on disk (no mocks):
  S7  compaction bracket (compaction/start|summary|end) with shadowed seqs,
      provider/model/token snapshot, and rebuild after a fresh reopen
  S8  compaction policy: 0.8 threshold / 0.16 retain defaults and the
      per-provider / per-provider-model override contract
  S12 durable projection cache ``session_projcache`` rows (key, version, value)
      with trigger-driven invalidation across a reopen
  S18 spill contract: save_text returns {locator, bytes, hint} and a failed
      write returns None so callers retain the original text

Run:  python scripts/w4_z3_session_proof.py <output.json>
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from atlas.engine.kernel.context import ContextManager
from atlas.engine.session_sync import (
    append_session_message,
    begin_session_compaction,
    compact_session_messages,
    read_session_model_messages,
)
from atlas.engine.state.atlas_state import SessionDB
from atlas.spill_store import save_text


def proof_s7_compaction_bracket(home: Path) -> dict:
    append_session_message(home, "s7", "user", "old request text")
    held = read_session_model_messages(home, "s7")
    watermark = begin_session_compaction(home, "s7", "w4-z3-proof")
    replacement = [{"role": "user", "content": "REBUILT_SUMMARY_TEXT", "_compressed_summary": True}]
    compact_session_messages(home, "s7", "w4-z3-proof", watermark, held, replacement,
                             snapshot_state={"provider": "deepseek", "model": "deepseek-v4.1-flash",
                                             "before_tokens": 1234})
    with SessionDB(db_path=home / "state.db") as db:
        events = db.list_session_events("s7")
    types = [event["event_type"] for event in events]
    summary = events[1]["payload"] if len(events) > 1 else {}
    rebuilt = read_session_model_messages(home, "s7")
    # Fresh reopen: the bracket and payload must still be durable and rebuildable.
    with SessionDB(db_path=home / "state.db") as db:
        events_again = db.list_session_events("s7")
    return {
        "event_types": types,
        "summary_keys": sorted(summary.keys()),
        "shadowed_seqs": summary.get("shadowed_seqs"),
        "shadowed_message_ids": summary.get("shadowed_message_ids"),
        "snapshot": summary.get("snapshot"),
        "model_history_after": [message["content"] for message in rebuilt],
        "durable_after_reopen": [event["event_type"] for event in events_again] == types,
    }


def proof_s8_policy() -> dict:
    default = ContextManager({}, provider="deepseek", model="deepseek-v4.1-flash")
    overridden = ContextManager({"context_compaction": {"overrides": {
        "deepseek": {"threshold_ratio": 0.7},
        "deepseek/deepseek-v4.1-flash": {"retain_ratio": 0.2},
    }}}, provider="deepseek", model="deepseek-v4.1-flash")
    thresholds_default = default.thresholds(100_000)
    thresholds_overridden = overridden.thresholds(100_000)
    return {
        "default_policy": default.compaction_policy,
        "default_auto_compact_of_100k": thresholds_default.auto_compact,
        "overridden_policy": overridden.compaction_policy,
        "overridden_auto_compact_of_100k": thresholds_overridden.auto_compact,
    }


def proof_s12_projcache(home: Path) -> dict:
    append_session_message(home, "s12", "user", "cache me")
    first = read_session_model_messages(home, "s12")
    with SessionDB(db_path=home / "state.db") as db:
        rows = [dict(row) for row in db._read_rows(
            "SELECT session_id, key, ver, seq, LENGTH(val) AS bytes FROM session_projcache")]
        revision = db.projection_revision("s12")
        cached = db.read_projection_cache("s12", "model_history", 1)
    append_session_message(home, "s12", "user", "second message")
    with SessionDB(db_path=home / "state.db") as db:
        rows_after = [dict(row) for row in db._read_rows(
            "SELECT session_id, key, ver, seq, LENGTH(val) AS bytes FROM session_projcache")]
        invalidated = db.read_projection_cache("s12", "model_history", 1)
        refreshed = read_session_model_messages(home, "s12")
    return {
        "cache_rows_after_first_read": rows,
        "cache_hit_on_reopen": cached == first,
        "projection_revision": revision,
        "cache_rows_after_update": rows_after,
        "invalidated_after_update": invalidated is None,
        "model_history_after_second_append": [message["content"] for message in refreshed],
    }


def proof_s18_spill(home: Path) -> dict:
    text = "SPILL-PROOF-" + ("x" * 4096)
    saved = save_text(text, directory=home / "spill")
    from atlas.engine.tools.spill_safety import ensure_spill_dir  # noqa: F401  (import sanity only)
    locator_path = None
    if saved:
        locator_path = saved["locator"].replace("file:///", "").replace("file://", "")
        readable = Path(locator_path).read_text(encoding="utf-8")
    else:
        readable = None
    # Failure contract: a parent that cannot become a directory (a plain file
    # occupies the path) must make save_text return None, never a locator.
    (home / "blocked").write_text("not a directory", encoding="utf-8")
    blocked = save_text(text, directory=home / "blocked" / "deeper")
    return {
        "saved_keys": sorted(saved.keys()) if saved else None,
        "bytes": saved["bytes"] if saved else None,
        "locator_is_file_uri": bool(saved and saved["locator"].startswith("file://")),
        "hint_exists": bool(saved and Path(locator_path).exists()),
        "roundtrip_matches": readable == text,
        "failed_write_returns_none": blocked is None,
    }


def main() -> int:
    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("w4_z3_session_proof.json")
    report: dict[str, dict] = {}
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "engine"
        home.mkdir(parents=True)
        report["S7_compaction_bracket"] = proof_s7_compaction_bracket(home)
        report["S12_projcache"] = proof_s12_projcache(home)
        report["S18_spill"] = proof_s18_spill(home)
    report["S8_compaction_policy"] = proof_s8_policy()
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    ok = (
        report["S7_compaction_bracket"]["event_types"] == ["compaction/start", "compaction/summary", "compaction/end"]
        and report["S7_compaction_bracket"]["durable_after_reopen"]
        and report["S12_projcache"]["cache_hit_on_reopen"]
        and report["S12_projcache"]["invalidated_after_update"]
        and report["S18_spill"]["failed_write_returns_none"]
        and report["S18_spill"]["roundtrip_matches"]
    )
    print("PROOF_OK" if ok else "PROOF_FAILED", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
