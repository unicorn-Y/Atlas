"""Portable ZIP snapshots of a session subtree and immutable attachment bytes."""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Callable


def build_session_archive(home: Path, session_id: str, *, flush: Callable[[], None] | None = None) -> bytes:
    """Flush the caller's live root first, then export its durable subtree.

    The optional callback belongs to the host holding the live root; its failure
    aborts export. SQLite transcript writes already commit synchronously.
    Missing or corrupted attachments also fail, never silently omit bytes.
    """
    from atlas.engine.session_sync import _open_db

    if flush is not None:
        flush()
    home = Path(home)
    documents = []
    with _open_db(home) as db:
        if not db.flush_token_counts():
            raise RuntimeError("Session flush timed out")
        todo = [session_id]
        seen = set()
        while todo:
            current = todo.pop(0)
            if current in seen:
                continue
            seen.add(current)
            document = db.export_session(current, include_compacted=False, include_inactive=True)
            if document is None:
                raise ValueError("Session transcript not found")
            events = []
            cursor = 0
            while True:
                page = db.list_session_events(current, after_seq=cursor, limit=10_000)
                events.extend(page)
                if len(page) < 10_000:
                    break
                cursor = page[-1]["seq"]
            document["events"] = events
            documents.append(document)
            todo.extend(str(row["id"]) for row in db._read_rows(
                "SELECT id FROM sessions WHERE parent_session_id = ? ORDER BY id", (current,)))
    encoded = json.dumps({"export_format": "atlas.session.zip.v1", "root_session_id": session_id,
                          "sessions": documents}, ensure_ascii=False, default=str).encode("utf-8")
    attachments = sorted(set(re.findall(rb'atlas-attachment://([^"\\\s]+)', encoded)))
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", encoded)
        for raw_digest in attachments:
            digest = raw_digest.decode("ascii")
            if not re.fullmatch("[0-9a-f]{64}", digest):
                raise ValueError("Invalid session attachment reference")
            payload = (home / "attachments" / digest[:2] / digest).read_bytes()
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("Session attachment failed integrity verification")
            archive.writestr(f"attachments/{digest[:2]}/{digest}", payload)
    return output.getvalue()
