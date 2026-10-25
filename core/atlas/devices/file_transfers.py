"""Durable, capability-gated file transfers between paired Atlas devices."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_CHUNK_BYTES = 1024 * 1024
TRANSFER_TTL_HOURS = 24


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


class FileTransferStore:
    """SQLite metadata/audit and isolated payload files under a local data directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.root / "transfers.sqlite", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS transfers (
                id TEXT PRIMARY KEY, source_device TEXT NOT NULL, target_device TEXT NOT NULL,
                filename TEXT NOT NULL, expected_size INTEGER NOT NULL, expected_sha256 TEXT NOT NULL,
                state TEXT NOT NULL, received_size INTEGER NOT NULL DEFAULT 0,
                actual_sha256 TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                accepted_at TEXT, completed_at TEXT, cancelled_at TEXT, error TEXT NOT NULL DEFAULT '')""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS transfer_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, transfer_id TEXT NOT NULL,
                event TEXT NOT NULL, actor_device TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS device_transfer_credentials (
                device_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, created_at TEXT NOT NULL)""")

    def issue_credential(self, device_id: str) -> str:
        token = secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock, self._db:
            self._db.execute("INSERT INTO device_transfer_credentials(device_id,token_hash,created_at) VALUES(?,?,?) "
                             "ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash,created_at=excluded.created_at",
                             (device_id, digest, _iso()))
        return token

    def verify_credential(self, device_id: str, token: str) -> bool:
        if not token:
            return False
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with self._lock:
            row = self._db.execute("SELECT token_hash FROM device_transfer_credentials WHERE device_id=?",
                                   (device_id,)).fetchone()
        return bool(row and secrets.compare_digest(str(row[0]), digest))

    def revoke_device(self, device_id: str) -> int:
        with self._lock, self._db:
            self._db.execute("DELETE FROM device_transfer_credentials WHERE device_id=?", (device_id,))
            rows = self._db.execute("SELECT id FROM transfers WHERE (source_device=? OR target_device=?) "
                                    "AND state IN ('awaiting_confirmation','uploading','ready')",
                                    (device_id, device_id)).fetchall()
            now = _iso()
            for row in rows:
                self._db.execute("UPDATE transfers SET state='cancelled',cancelled_at=?,error='device removed' WHERE id=?",
                                 (now, row["id"]))
                self._event(row["id"], "device_removed", device_id, "transfer cancelled because paired device was removed")
                (self.root / f"{row['id']}.part").unlink(missing_ok=True)
        return len(rows)

    def _event(self, transfer_id: str, event: str, actor: str, detail: str = "") -> None:
        self._db.execute("INSERT INTO transfer_events(transfer_id,event,actor_device,detail,created_at) VALUES(?,?,?,?,?)",
                         (transfer_id, event, actor, detail[:400], _iso()))

    def create(self, source: str, target: str, filename: str, size: int, sha256: str) -> dict[str, Any]:
        if not source or not target or source == target:
            raise ValueError("source and distinct target device ids are required")
        if size < 1 or size > MAX_FILE_BYTES:
            raise ValueError(f"file size must be between 1 and {MAX_FILE_BYTES} bytes")
        name = Path(filename.replace("\\", "/")).name.strip()
        if not name or name in {".", ".."} or len(name) > 240:
            raise ValueError("invalid filename")
        digest = sha256.strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("sha256 must be a 64-character hex digest")
        transfer_id = uuid.uuid4().hex
        now = _now()
        with self._lock, self._db:
            self._db.execute("INSERT INTO transfers(id,source_device,target_device,filename,expected_size,expected_sha256,state,created_at,expires_at) VALUES(?,?,?,?,?,?,?,?,?)",
                             (transfer_id, source, target, name, size, digest, "awaiting_confirmation", _iso(now), _iso(now + timedelta(hours=TRANSFER_TTL_HOURS))))
            self._event(transfer_id, "requested", source, f"target={target}; filename={name}; size={size}; sha256={digest}")
        return self.get(transfer_id) or {}

    def get(self, transfer_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
            if row and row["state"] not in {"completed", "cancelled", "expired", "failed"}:
                try:
                    expired = datetime.fromisoformat(str(row["expires_at"])) <= _now()
                except ValueError:
                    expired = True
                if expired:
                    with self._db:
                        self._db.execute("UPDATE transfers SET state='expired',error='request expired' WHERE id=?",
                                         (transfer_id,))
                        self._event(transfer_id, "expired", "system")
                    (self.root / f"{transfer_id}.part").unlink(missing_ok=True)
                    row = self._db.execute("SELECT * FROM transfers WHERE id=?", (transfer_id,)).fetchone()
        return dict(row) if row else None

    def list(self, device_id: str) -> list[dict[str, Any]]:
        self.cleanup()
        with self._lock:
            rows = self._db.execute("SELECT * FROM transfers WHERE source_device=? OR target_device=? ORDER BY created_at DESC",
                                    (device_id, device_id)).fetchall()
        return [dict(row) for row in rows]

    def events(self, transfer_id: str) -> list[dict[str, str]]:
        with self._lock:
            rows = self._db.execute("SELECT event,actor_device,detail,created_at FROM transfer_events WHERE transfer_id=? ORDER BY id",
                                    (transfer_id,)).fetchall()
        return [dict(row) for row in rows]

    def _require_state(self, transfer_id: str, states: set[str]) -> dict[str, Any]:
        row = self.get(transfer_id)
        if row is None:
            raise KeyError("transfer not found")
        if row["state"] not in states:
            raise ValueError(f"transfer state is {row['state']}")
        return row

    def accept(self, transfer_id: str, device_id: str) -> dict[str, Any]:
        with self._lock, self._db:
            row = self._require_state(transfer_id, {"awaiting_confirmation"})
            if device_id != row["target_device"]:
                raise PermissionError("only the target device can accept this transfer")
            self._db.execute("UPDATE transfers SET state='uploading',accepted_at=? WHERE id=?", (_iso(), transfer_id))
            self._event(transfer_id, "accepted", device_id)
        return self.get(transfer_id) or {}

    def upload_path(self, transfer_id: str, device_id: str) -> tuple[dict[str, Any], Path]:
        row = self._require_state(transfer_id, {"uploading"})
        if row["source_device"] != device_id:
            raise PermissionError("only the source device can upload this transfer")
        return row, self.root / f"{transfer_id}.part"

    def append_chunk(self, transfer_id: str, device_id: str, offset: int, data: bytes) -> dict[str, Any]:
        if not data or len(data) > MAX_CHUNK_BYTES:
            raise ValueError(f"chunk must contain 1-{MAX_CHUNK_BYTES} bytes")
        with self._lock:
            row, path = self.upload_path(transfer_id, device_id)
            if offset != int(row["received_size"]):
                raise ValueError(f"unexpected upload offset; expected {row['received_size']}")
            if offset + len(data) > int(row["expected_size"]):
                raise ValueError("chunk exceeds declared file size")
            mode = "wb" if offset == 0 else "ab"
            with path.open(mode) as output:
                output.write(data)
            size = offset + len(data)
            with self._db:
                self._db.execute("UPDATE transfers SET received_size=? WHERE id=? AND state='uploading'",
                                 (size, transfer_id))
            if size < int(row["expected_size"]):
                self._event(transfer_id, "progress", device_id, f"received={size}")
                return self.get(transfer_id) or {}
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(MAX_CHUNK_BYTES):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            try:
                return self.mark_uploaded(transfer_id, device_id, size, digest)
            except ValueError:
                path.unlink(missing_ok=True)
                raise

    def mark_uploaded(self, transfer_id: str, device_id: str, size: int, digest: str) -> dict[str, Any]:
        with self._lock, self._db:
            row = self._require_state(transfer_id, {"uploading"})
            if row["source_device"] != device_id:
                raise PermissionError("only the source device can complete this transfer")
            if size != row["expected_size"] or digest != row["expected_sha256"]:
                self._db.execute("UPDATE transfers SET state='failed',received_size=?,actual_sha256=?,error='size or sha256 mismatch' WHERE id=?",
                                 (size, digest, transfer_id))
                self._event(transfer_id, "integrity_failed", device_id, f"size={size}; sha256={digest}")
                raise ValueError("uploaded file does not match declared size or sha256")
            self._db.execute("UPDATE transfers SET state='ready',received_size=?,actual_sha256=? WHERE id=?",
                             (size, digest, transfer_id))
            self._event(transfer_id, "upload_verified", device_id, f"size={size}; sha256={digest}")
        return self.get(transfer_id) or {}

    def payload_path(self, transfer_id: str, device_id: str) -> tuple[dict[str, Any], Path]:
        row = self._require_state(transfer_id, {"ready"})
        if row["target_device"] != device_id:
            raise PermissionError("only the target device can download this transfer")
        return row, self.root / f"{transfer_id}.part"

    def complete(self, transfer_id: str, device_id: str) -> dict[str, Any]:
        with self._lock, self._db:
            row = self._require_state(transfer_id, {"ready"})
            if row["target_device"] != device_id:
                raise PermissionError("only the target device can complete this transfer")
            self._db.execute("UPDATE transfers SET state='completed',completed_at=? WHERE id=?", (_iso(), transfer_id))
            self._event(transfer_id, "downloaded", device_id)
        (self.root / f"{transfer_id}.part").unlink(missing_ok=True)
        return self.get(transfer_id) or {}

    def cancel(self, transfer_id: str, device_id: str) -> dict[str, Any]:
        with self._lock, self._db:
            row = self._require_state(transfer_id, {"awaiting_confirmation", "uploading", "ready"})
            if device_id not in {row["source_device"], row["target_device"]}:
                raise PermissionError("only participating devices can cancel this transfer")
            self._db.execute("UPDATE transfers SET state='cancelled',cancelled_at=? WHERE id=?", (_iso(), transfer_id))
            self._event(transfer_id, "cancelled", device_id)
        (self.root / f"{transfer_id}.part").unlink(missing_ok=True)
        return self.get(transfer_id) or {}

    def cleanup(self) -> int:
        now = _iso()
        with self._lock, self._db:
            rows = self._db.execute("SELECT id FROM transfers WHERE expires_at<? AND state NOT IN ('completed','cancelled','expired')", (now,)).fetchall()
            for row in rows:
                self._db.execute("UPDATE transfers SET state='expired',error='request expired' WHERE id=?", (row["id"],))
                self._event(row["id"], "expired", "system")
                (self.root / f"{row['id']}.part").unlink(missing_ok=True)
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._db.close()
