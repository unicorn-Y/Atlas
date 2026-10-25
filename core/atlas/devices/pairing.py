"""Short-lived device and DM pairing requests, plus authenticated inbox delivery."""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import threading
from contextlib import contextmanager
import uuid
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class PairingStore:
    _key_lock = threading.Lock()

    def __init__(self, path: Path, *, clock=time.time) -> None:
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
              CREATE TABLE IF NOT EXISTS device_challenges (
                id TEXT PRIMARY KEY, code_hash TEXT NOT NULL, expires REAL NOT NULL,
                used INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS pairing_requests (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, device_id TEXT NOT NULL,
                display_name TEXT NOT NULL, os TEXT NOT NULL DEFAULT '',
                channel TEXT NOT NULL DEFAULT '', code_hash TEXT NOT NULL,
                proof_hash TEXT NOT NULL, status TEXT NOT NULL, expires REAL NOT NULL,
                credential TEXT NOT NULL DEFAULT '', credential_hash TEXT NOT NULL DEFAULT '', created REAL NOT NULL, delivered INTEGER NOT NULL DEFAULT 0);
              CREATE TABLE IF NOT EXISTS device_commands (
                id TEXT PRIMARY KEY, device_id TEXT NOT NULL, prompt TEXT NOT NULL,
                status TEXT NOT NULL, result TEXT NOT NULL DEFAULT '', created REAL NOT NULL,
                updated REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS device_tokens (
                device_id TEXT PRIMARY KEY, token_hash TEXT NOT NULL, updated REAL NOT NULL);
            """)
            columns = {str(row[1]) for row in db.execute("PRAGMA table_info(pairing_requests)")}
            if "credential_hash" not in columns:
                db.execute("ALTER TABLE pairing_requests ADD COLUMN credential_hash TEXT NOT NULL DEFAULT ''")
            challenge_columns = {str(row[1]) for row in db.execute("PRAGMA table_info(device_challenges)")}
            if "attempts" not in challenge_columns:
                db.execute("ALTER TABLE device_challenges ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")

    def _fernet(self) -> Fernet:
        key_path = self.path.with_suffix(".key")
        with self._key_lock:
            if not key_path.exists():
                key_path.parent.mkdir(parents=True, exist_ok=True)
                key_path.write_bytes(Fernet.generate_key())
                try:
                    key_path.chmod(0o600)
                except OSError:
                    pass
            return Fernet(key_path.read_bytes())

    def _seal(self, value: str) -> str:
        return self._fernet().encrypt(value.encode("utf-8")).decode("ascii")

    def _open(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, UnicodeError) as exc:
            raise RuntimeError("配对凭据无法解密") from exc

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def _connection(self):
        db = self._connect()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def create_device_challenge(self, ttl: int = 120) -> dict[str, Any]:
        challenge_id, code = uuid.uuid4().hex, f"{secrets.randbelow(100_000_000):08d}"
        now = self.clock()
        with self._connection() as db:
            db.execute("DELETE FROM device_challenges WHERE expires<? OR used=1", (now,))
            db.execute("INSERT INTO device_challenges(id,code_hash,expires,created) VALUES(?,?,?,?)",
                       (challenge_id, self._hash(code), now + ttl, now))
        return {"challenge_id": challenge_id, "code": code, "expires_at": now + ttl}

    def claim_device(self, challenge_id: str, code: str, device_id: str,
                     display_name: str, os_name: str = "") -> dict[str, str]:
        request_id, proof = uuid.uuid4().hex, secrets.token_urlsafe(32)
        now = self.clock()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            challenge = db.execute("SELECT * FROM device_challenges WHERE id=?", (challenge_id,)).fetchone()
            if not challenge or challenge["used"] or challenge["expires"] < now:
                raise ValueError("配对码无效或已过期，请在 Atlas 设备页重新生成二维码。")
            if not secrets.compare_digest(str(challenge["code_hash"]), self._hash(code.strip())):
                attempts = int(challenge["attempts"]) + 1
                db.execute("UPDATE device_challenges SET attempts=?,used=? WHERE id=?", (attempts, int(attempts >= 5), challenge_id))
                db.commit()
                raise ValueError("配对码无效或已过期，请在 Atlas 设备页重新生成二维码。")
            if db.execute("SELECT 1 FROM pairing_requests WHERE kind='device' AND device_id=? AND status IN ('pending','approved') AND expires>=?",
                          (device_id, now)).fetchone():
                raise ValueError("此设备已有未完成的配对申请。")
            db.execute("UPDATE device_challenges SET used=1 WHERE id=?", (challenge_id,))
            db.execute("INSERT INTO pairing_requests(id,kind,device_id,display_name,os,code_hash,proof_hash,status,expires,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (request_id, "device", device_id, display_name[:120], os_name[:120],
                        challenge["code_hash"], self._hash(proof), "pending", now + 600, now))
        return {"request_id": request_id, "proof": proof, "status": "pending"}

    def create_dm_request(self, channel: str, sender_id: str, display_name: str = "") -> str | None:
        now, code = self.clock(), f"{secrets.randbelow(100_000_000):08d}"
        request_id, proof = uuid.uuid4().hex, secrets.token_urlsafe(24)
        with self._connection() as db:
            db.execute("DELETE FROM pairing_requests WHERE expires<? OR status IN ('rejected','expired','delivered')", (now,))
            existing = db.execute("SELECT id FROM pairing_requests WHERE kind='dm' AND channel=? AND device_id=? AND status IN ('pending','approved') AND expires>=?",
                                  (channel, sender_id, now)).fetchone()
            if existing:
                return None
            db.execute("INSERT INTO pairing_requests(id,kind,device_id,display_name,channel,code_hash,proof_hash,status,expires,created) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (request_id, "dm", sender_id[:128], display_name[:120], channel[:80],
                        self._hash(code), self._hash(proof), "pending", now + 86400, now))
        return code

    def list_requests(self, kind: str = "") -> list[dict[str, Any]]:
        now = self.clock()
        with self._connection() as db:
            db.execute("UPDATE pairing_requests SET status='expired' WHERE status IN ('pending','approved') AND expires<?", (now,))
            predicate = ("status IN ('pending','approved')" if kind == "dm" else "status='pending'" if kind == "device"
                         else "(status='pending' OR (kind='dm' AND status='approved'))")
            query = f"SELECT id,kind,device_id,display_name,os,channel,status,expires,created FROM pairing_requests WHERE {predicate}"
            rows = db.execute(query + (" AND kind=?" if kind else "") + " ORDER BY created DESC", ((kind,) if kind else ())).fetchall()
        return [dict(row) for row in rows]

    def decide(self, request_id: str, action: str, credential: str = "") -> dict[str, Any]:
        if action not in {"approve", "reject", "expire", "revoke"}:
            raise ValueError("action must be approve, reject, expire, or revoke")
        with self._connection() as db:
            row = db.execute("SELECT * FROM pairing_requests WHERE id=?", (request_id,)).fetchone()
            allowed_status = row and (row["status"] == "pending" or (action == "revoke" and row["status"] == "approved"))
            if not allowed_status or row["expires"] < self.clock():
                raise KeyError("配对请求不存在或已失效")
            if row["kind"] == "dm" and action == "approve":
                status = "approved"
            else:
                status = {"approve": "approved", "reject": "rejected", "expire": "expired", "revoke": "revoked"}[action]
            credential_hash = self._hash(credential) if row["kind"] == "device" and action == "approve" else ""
            encrypted = self._seal(credential) if credential_hash else ""
            db.execute("UPDATE pairing_requests SET status=?,credential=?,credential_hash=? WHERE id=?",
                       (status, encrypted, credential_hash, request_id))
            if credential_hash:
                db.execute("INSERT INTO device_tokens(device_id,token_hash,updated) VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash,updated=excluded.updated",
                           (row["device_id"], credential_hash, self.clock()))
            return {key: row[key] for key in ("id", "kind", "device_id", "display_name", "os", "channel")} | {"status": status}

    def claim_status(self, request_id: str, proof: str) -> dict[str, Any]:
        with self._connection() as db:
            row = db.execute("SELECT * FROM pairing_requests WHERE id=? AND kind='device'", (request_id,)).fetchone()
            if not row or not secrets.compare_digest(str(row["proof_hash"]), self._hash(proof)):
                raise KeyError("配对请求不存在")
            result: dict[str, Any] = {"status": row["status"]}
            if row["status"] == "approved" and not row["delivered"] and row["credential"]:
                result.update({"device_id": row["device_id"], "credential": self._open(row["credential"])})
                db.execute("UPDATE pairing_requests SET credential='',delivered=1,status='delivered' WHERE id=?", (request_id,))
            return result

    def verify_credential(self, device_id: str, credential: str) -> bool:
        with self._connection() as db:
            row = db.execute("SELECT token_hash FROM device_tokens WHERE device_id=?", (device_id,)).fetchone()
        return bool(row and secrets.compare_digest(str(row[0]), self._hash(credential)))

    def has_credential(self, device_id: str) -> bool:
        with self._connection() as db:
            return db.execute("SELECT 1 FROM device_tokens WHERE device_id=?", (device_id,)).fetchone() is not None

    def rotate_credential(self, device_id: str) -> str:
        credential = secrets.token_urlsafe(40)
        with self._connection() as db:
            db.execute("INSERT INTO device_tokens(device_id,token_hash,updated) VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash,updated=excluded.updated",
                       (device_id, self._hash(credential), self.clock()))
        return credential

    def revoke_credential(self, device_id: str) -> None:
        with self._connection() as db:
            db.execute("DELETE FROM device_tokens WHERE device_id=?", (device_id,))

    def pending_commands(self, device_id: str) -> list[dict[str, Any]]:
        now = self.clock()
        with self._connection() as db:
            rows = db.execute("SELECT id,device_id,prompt,status,created,updated FROM device_commands WHERE device_id=? AND status IN ('pending','delivered') ORDER BY created LIMIT 100", (device_id,)).fetchall()
            db.executemany("UPDATE device_commands SET status='delivered',updated=? WHERE id=? AND status='pending'", ((now, row["id"]) for row in rows))
        return [dict(row) | {"status": "delivered"} for row in rows]

    def approved_dm_ids(self, channel: str) -> list[str]:
        now = self.clock()
        with self._connection() as db:
            return [str(row[0]) for row in db.execute(
                "SELECT device_id FROM pairing_requests WHERE kind='dm' AND channel=? AND status='approved' AND expires>=?",
                (channel, now)).fetchall()]

    def create_command(self, device_id: str, prompt: str) -> dict[str, Any]:
        now, command_id = self.clock(), uuid.uuid4().hex
        with self._connection() as db:
            db.execute("INSERT INTO device_commands(id,device_id,prompt,status,created,updated) VALUES(?,?,?,'pending',?,?)",
                       (command_id, device_id, prompt[:8000], now, now))
        return {"id": command_id, "device_id": device_id, "prompt": prompt[:8000], "status": "pending"}

    def list_commands(self, device_id: str) -> list[dict[str, Any]]:
        with self._connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT id,device_id,prompt,status,result,created,updated FROM device_commands WHERE device_id=? ORDER BY created DESC LIMIT 100",
                (device_id,)).fetchall()]

    def complete_command(self, device_id: str, command_id: str, result: str) -> dict[str, Any]:
        with self._connection() as db:
            cur = db.execute("UPDATE device_commands SET status='completed',result=?,updated=? WHERE id=? AND device_id=? AND status IN ('pending','delivered')",
                             (result[:12000], self.clock(), command_id, device_id))
            if not cur.rowcount:
                raise KeyError("指令不存在或已完成")
            return dict(db.execute("SELECT id,device_id,prompt,status,result,created,updated FROM device_commands WHERE id=?", (command_id,)).fetchone())


__all__ = ["PairingStore"]
