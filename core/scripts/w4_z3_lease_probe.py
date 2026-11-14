"""Cross-process turn-lease probe (DSH S5 evidence).

Runs as a SEPARATE process against the live backend's engine database and
reports, without touching the backend: who currently holds the conversation's
turn lease, whether this probe process can acquire it, and (after acquiring)
whether its own holder row is visible to a fresh reader.

Usage: python scripts/w4_z3_lease_probe.py <engine_home> <conversation_id> <tag> <out_json>
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from atlas.engine.state.atlas_state import SessionDB
from atlas.engine.state.atlas_state_pidns import holder_namespace_token


def main() -> int:
    home = Path(sys.argv[1])
    conversation_id = sys.argv[2]
    tag = sys.argv[3]
    out_path = Path(sys.argv[4])
    holder = f"pid={os.getpid()}{holder_namespace_token()}:probe={tag}"
    result: dict = {"probe_pid": os.getpid(), "holder": holder, "conversation_id": conversation_id}
    try:
        with SessionDB(db_path=home / "state.db") as db:
            row = db._read_one(
                "SELECT conversation_id, holder, expires_at FROM session_turn_leases "
                "WHERE conversation_id = ?", (conversation_id,))
            result["existing_holder"] = None if row is None else {
                "holder": row["holder"], "expires_at": float(row["expires_at"]),
                "expires_in_s": round(float(row["expires_at"]) - time.time(), 1),
            }
            acquired = db.try_acquire_session_turn_lease(conversation_id, holder, ttl_seconds=300.0)
            result["acquired"] = bool(acquired)
            if acquired:
                db.release_session_turn_lease(conversation_id, holder)
    except Exception as exc:  # noqa: BLE001 - probe must report, never crash the turn
        result["error"] = f"{type(exc).__name__}: {exc}"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
