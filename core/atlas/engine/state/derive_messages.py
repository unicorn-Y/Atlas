"""Project model history from the append-only event log.

The ledger's E1/S1 asks for the DSH property: the session log is the source of
truth and model history is *derived* from it. Atlas stores history in mutable
`messages` rows instead, so this module answers a narrower, checkable question:

    Can the event log alone reconstruct what the model saw?

It can now, because every `append_message` writes a `message/append` event in the
same transaction. `derive_messages` folds those events back into the same shape
`read_session_model_messages` returns, and `compare_projection` diffs the two.

What this deliberately does **not** claim: that the event log has become the
canonical store. Compaction and rewind deactivate rows with an `UPDATE` that
emits `messages.deactivated` rather than a transcript event, so a derived history
must also consult those events to know what is still live. `compare_projection`
surfaces exactly that difference instead of hiding it, which is why it returns a
diff list rather than a boolean.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

__all__ = [
    "derive_messages",
    "compare_projection",
    "DEACTIVATED_EVENT",
    "MESSAGE_EVENT",
]

MESSAGE_EVENT = "message/append"
DEACTIVATED_EVENT = "messages.deactivated"


def _payload(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("payload") or event.get("payload_json") or {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


def derive_messages(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Fold `message/append` events into a model-history-shaped list.

    A `messages.deactivated` event removes the referenced message from the
    derived history, which is how compaction and rewind stay visible here: the
    original append is never rewritten, it is superseded.
    """
    appended: list[dict[str, Any]] = []
    deactivated: set[str] = set()
    for event in events:
        kind = str(event.get("event_type") or event.get("kind") or "")
        payload = _payload(event)
        if kind == MESSAGE_EVENT:
            message_id = payload.get("message_id")
            appended.append({
                "id": message_id,
                "role": str(payload.get("role") or ""),
                "tool_name": payload.get("tool_name"),
                "tool_call_id": payload.get("tool_call_id"),
                "has_tool_calls": bool(payload.get("has_tool_calls")),
            })
        elif kind == DEACTIVATED_EVENT:
            for message_id in payload.get("message_ids") or (
                [payload.get("message_id")] if payload.get("message_id") else []
            ):
                deactivated.add(str(message_id))
    return [m for m in appended if str(m["id"]) not in deactivated]


def compare_projection(
    events: Iterable[Mapping[str, Any]],
    legacy_messages: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Diff the derived history against the rows the model path actually reads.

    Returns the differences rather than a boolean: "the projection disagrees"
    is only useful if the caller can see *where*, and a difference caused by a
    deactivation the log does not record is a real, reportable finding.
    """
    derived = derive_messages(events)
    legacy_ids = [str(m.get("_row_id") or m.get("id") or "") for m in legacy_messages]
    derived_ids = [str(m["id"]) for m in derived]
    differences: list[dict[str, Any]] = []
    for index in range(max(len(derived_ids), len(legacy_ids))):
        left = derived_ids[index] if index < len(derived_ids) else None
        right = legacy_ids[index] if index < len(legacy_ids) else None
        if left != right:
            differences.append({
                "index": index, "derived_id": left, "legacy_id": right,
                "reason": ("missing from the log" if left is None
                           else "missing from the live rows" if right is None
                           else "order or identity differs"),
            })
    return {
        "derived_count": len(derived_ids),
        "legacy_count": len(legacy_ids),
        "match": not differences,
        "differences": differences,
    }
