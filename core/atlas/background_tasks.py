"""Idle queue and IMAP trigger primitives used by Atlas background scheduling."""
from __future__ import annotations

from datetime import datetime, time as dt_time
from email import message_from_bytes
from email.header import decode_header, make_header
from email.utils import parseaddr
import imaplib
import json
from pathlib import Path
import sqlite3
from typing import Any


def in_idle_window(now: datetime, start: str = "01:00", end: str = "07:00") -> bool:
    begin = dt_time.fromisoformat(start); finish = dt_time.fromisoformat(end)
    current = now.timetz().replace(tzinfo=None)
    return begin <= current < finish if begin <= finish else current >= begin or current < finish


def idle_ready(*, now: datetime, start: str, end: str, idle_minutes: int,
               seconds_since_input: float | None) -> bool:
    return in_idle_window(now, start, end) or (
        seconds_since_input is not None and seconds_since_input >= idle_minutes * 60
    )


def _decode(value: str | None) -> str:
    if not value:
        return ""
    try: return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError, ValueError): return value


def email_summary(raw: bytes) -> dict[str, str]:
    message = message_from_bytes(raw)
    body = ""
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True)
                if payload:
                    body = payload.decode(part.get_content_charset() or "utf-8", errors="replace"); break
    else:
        payload = message.get_payload(decode=True)
        if payload:
            body = payload.decode(message.get_content_charset() or "utf-8", errors="replace")
    sender = _decode(message.get("From"))
    return {"message_id": str(message.get("Message-ID", "")).strip(), "sender": sender,
            "sender_address": parseaddr(sender)[1], "subject": _decode(message.get("Subject")),
            "body_summary": " ".join(body.split())[:2000]}


def match_email_rule(message: dict[str, str], rule: dict[str, Any]) -> bool:
    sender = str(rule.get("sender", "")).casefold()
    subject = str(rule.get("subject", "")).casefold()
    keyword = str(rule.get("keyword", "")).casefold()
    return (not sender or sender in message["sender_address"].casefold()) and (
        not subject or subject in message["subject"].casefold()) and (
        not keyword or keyword in (message["subject"] + " " + message["body_summary"]).casefold())


class IdleTaskQueue:
    def __init__(self, path: Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS idle_tasks (id TEXT PRIMARY KEY, prompt TEXT NOT NULL, workspace TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'queued', run_id TEXT NOT NULL DEFAULT '', run_now INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(idle_tasks)")}
            if "run_now" not in columns: db.execute("ALTER TABLE idle_tasks ADD COLUMN run_now INTEGER NOT NULL DEFAULT 0")

    def list(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM idle_tasks ORDER BY position,created_at")]

    def add(self, task_id: str, prompt: str, workspace: str = "") -> dict[str, Any]:
        if not task_id.strip() or not prompt.strip(): raise ValueError("task id and prompt are required")
        with sqlite3.connect(self.path) as db:
            pos = db.execute("SELECT COALESCE(MAX(position),0)+1 FROM idle_tasks").fetchone()[0]
            db.execute("INSERT INTO idle_tasks(id,prompt,workspace,position) VALUES(?,?,?,?)", (task_id, prompt, workspace, pos))
        return next(row for row in self.list() if row["id"] == task_id)

    def reorder(self, task_ids: list[str]) -> None:
        rows = {row["id"]: row for row in self.list()}
        if len(task_ids) != len(rows) or set(task_ids) != set(rows): raise ValueError("order must include each queued task exactly once")
        with sqlite3.connect(self.path) as db:
            db.executemany("UPDATE idle_tasks SET position=? WHERE id=?", [(i, task_id) for i, task_id in enumerate(task_ids)])

    def remove(self, task_id: str) -> None:
        with sqlite3.connect(self.path) as db: db.execute("DELETE FROM idle_tasks WHERE id=?", (task_id,))

    def claim_next(self) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM idle_tasks WHERE status='queued' ORDER BY run_now DESC,position,created_at LIMIT 1").fetchone()
            if row is None: return None
            db.execute("UPDATE idle_tasks SET status='running' WHERE id=?", (row["id"],))
            return dict(row)

    def request_run_now(self, task_id: str) -> bool:
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("UPDATE idle_tasks SET run_now=1 WHERE id=? AND status='queued'", (task_id,))
            return cursor.rowcount > 0

    def set_status(self, task_id: str, status: str, run_id: str = "") -> None:
        if status not in {"queued", "running", "completed", "failed", "cancelled"}: raise ValueError("invalid idle task status")
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE idle_tasks SET status=?,run_id=? WHERE id=?", (status, run_id, task_id))


def seconds_since_input() -> float | None:
    """Windows keyboard/mouse idle duration; unknown on unsupported platforms."""
    if __import__("os").name != "nt": return None
    import ctypes
    from ctypes import wintypes

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]
    info = LASTINPUTINFO(); info.cbSize = ctypes.sizeof(info)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)): return None
    tick = ctypes.windll.kernel32.GetTickCount64()
    return max(0.0, (int(tick) - int(info.dwTime)) / 1000.0)


class EmailDeduplicator:
    def __init__(self, path: Path):
        self.path = Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute("CREATE TABLE IF NOT EXISTS seen_email_ids (message_id TEXT PRIMARY KEY, seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def first_seen(self, message_id: str) -> bool:
        if not message_id: return False
        with sqlite3.connect(self.path) as db:
            cursor = db.execute("INSERT OR IGNORE INTO seen_email_ids(message_id) VALUES(?)", (message_id,))
            return cursor.rowcount == 1


def fetch_matching_imap(server: str, username: str, password: str, rules: list[dict[str, Any]],
                        dedupe: EmailDeduplicator) -> list[dict[str, str]]:
    """Fetch unseen mail; credentials stay in the function call and are never logged."""
    mailbox = imaplib.IMAP4_SSL(server, timeout=20)
    try:
        mailbox.login(username, password)
        mailbox.select("INBOX", readonly=True)
        status, data = mailbox.search(None, "UNSEEN")
        if status != "OK": return []
        results = []
        for number in data[0].split():
            status, fetched = mailbox.fetch(number, "(RFC822)")
            if status != "OK": continue
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), None)
            if not raw: continue
            message = email_summary(raw)
            if not dedupe.first_seen(message["message_id"]): continue
            matching = [rule for rule in rules if match_email_rule(message, rule)]
            for rule in matching: results.append({**message, "task_prompt": str(rule.get("template", "{subject}\n{sender}\n{body_summary}")).format(**message)})
        return results
    finally:
        try: mailbox.logout()
        except (OSError, imaplib.IMAP4.error): pass


def mail_trigger_config() -> dict[str, Any]:
    from atlas.config import DATA_ROOT
    path = DATA_ROOT / "data" / "mail-trigger.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError): return {}


def save_mail_trigger_config(value: dict[str, Any], password: str | None = None) -> dict[str, Any]:
    from atlas.config import DATA_ROOT
    try:
        import keyring
    except ImportError as exc:
        raise RuntimeError("OS keyring support is unavailable") from exc
    path = DATA_ROOT / "data" / "mail-trigger.json"
    previous = mail_trigger_config()
    safe = {"enabled": bool(value.get("enabled")), "server": str(value.get("server", "")).strip(),
            "username": str(value.get("username", "")).strip(), "interval_seconds": int(value.get("interval_seconds", 300)),
            "rules": value.get("rules", [])}
    if not 30 <= safe["interval_seconds"] <= 86400 or not isinstance(safe["rules"], list):
        raise ValueError("interval_seconds must be 30..86400 and rules must be a list")
    if password:
        keyring.set_password("Atlas IMAP trigger", safe["username"], password)
    elif previous.get("username") and previous.get("username") != safe["username"]:
        try: keyring.delete_password("Atlas IMAP trigger", str(previous["username"]))
        except Exception: pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, ensure_ascii=False), encoding="utf-8")
    return safe


def get_mail_password(username: str) -> str | None:
    try:
        import keyring
        return keyring.get_password("Atlas IMAP trigger", username)
    except Exception:
        return None
