"""Versioned JSONL event stream used by ``atlas exec --json``."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any, TextIO


class ExecJSONLStream:
    """Write one complete, versioned event per line with monotonic item lifecycles."""

    protocol = "atlas.exec.events"
    version = 1

    def __init__(self, session_id: str, out: TextIO | None = None) -> None:
        self.session_id = session_id
        self.turn_id = str(uuid.uuid4())
        self.sequence = 0
        self._next_item = 0
        self._open_items: dict[str, dict[str, Any]] = {}
        self.out = out or sys.stdout

    def emit(self, event_type: str, **fields: Any) -> None:
        self.sequence += 1
        event = {
            "protocol": self.protocol,
            "version": self.version,
            "event_id": f"{self.turn_id}:{self.sequence}",
            "sequence": self.sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "type": event_type,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            **fields,
        }
        self.out.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        self.out.flush()

    def start_item(self, item_type: str, **item: Any) -> str:
        item_id = f"item_{self._next_item}"
        self._next_item += 1
        self._open_items[item_id] = {"type": item_type, **item}
        self.emit("item.started", item_id=item_id, item=self._open_items[item_id])
        return item_id

    def complete_item(self, item_id: str, item_type: str, **item: Any) -> None:
        started_item = self._open_items.pop(item_id, None)
        if started_item is None:
            raise ValueError(f"JSONL item is not open: {item_id}")
        self.emit("item.completed", item_id=item_id,
                  item={**started_item, **item, "type": item_type})

    def emit_legacy(self, event: dict[str, Any]) -> None:
        """Keep the established short event names while adding the v1 envelope."""
        fields = {key: value for key, value in event.items() if key != "type"}
        self.emit(str(event.get("type", "event")), **fields)

    def complete_open_items(self, *, reason: str = "turn_ended") -> None:
        for item_id in sorted(tuple(self._open_items)):
            started_item = self._open_items[item_id]
            self.complete_item(item_id, str(started_item["type"]), status="interrupted", reason=reason)
