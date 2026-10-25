"""Portable, single-file read-only conversation exports."""
from __future__ import annotations

from datetime import UTC, datetime, timezone
import html
import hashlib
import hmac
import json
from pathlib import Path
import re
import secrets
import sqlite3
from contextlib import closing
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

_SECRET = re.compile(r"(?i)(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,}|(?:token|api[_-]?key|password|secret)\s*[:=]\s*['\"]?[^\s'\"]{8,})")
_USER_PATH = re.compile(r"(?i)(?:[A-Z]:\\Users\\[^\\\s]+|/home/[^/\s]+|/Users/[^/\s]+)")


def redact(value: str) -> str:
    return _USER_PATH.sub("~", _SECRET.sub("[REDACTED]", value))


_ROLE_LABELS = {"user": "你", "assistant": "Atlas", "tool": "工具", "function": "工具", "thinking": "思考", "system": "系统"}


def _local_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M")


def _usage_text(usage: dict[str, Any] | None) -> str:
    if not usage:
        return "无记录"
    parts = [f"输入 {int(usage.get('input_tokens') or 0):,} / 输出 {int(usage.get('output_tokens') or 0):,} tokens"]
    if usage.get("cache_hit_rate") is not None:
        parts.append(f"缓存命中 {float(usage['cache_hit_rate']) * 100:.0f}%")
    cost = usage.get("est_cost") if usage.get("est_cost") is not None else usage.get("known_cost")
    if cost:
        parts.append(f"约 ${float(cost):.4f}")
    return "，".join(parts)


def export_html(path: Path, *, title: str, messages: list[dict[str, Any]],
                model: str = "", usage: dict[str, Any] | None = None,
                include_tools: bool = True, include_thinking: bool = False) -> Path:
    rows = []
    for item in messages:
        role = str(item.get("role", "assistant"))
        content = str(item.get("content", ""))
        metadata = item.get("metadata", {})
        if isinstance(metadata, str):
            try: metadata = json.loads(metadata)
            except json.JSONDecodeError: metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        if not model and role == "assistant" and metadata.get("model"):
            model = str(metadata.get("model"))
        is_tool = role in {"tool", "function"} or bool((metadata or {}).get("tool_calls"))
        is_thought = role == "thinking" or bool((metadata or {}).get("thinking"))
        if (is_tool and not include_tools) or (is_thought and not include_thinking):
            continue
        safe = html.escape(redact(content))
        safe = re.sub(
            r"!\[([^\]]*)\]\((data:image/(?:png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+)\)",
            lambda match: f'<img alt="{match.group(1)}" src="{match.group(2)}" style="max-width:100%">', safe,
        )
        if safe.startswith("diff --git") or "@@ -" in safe:
            safe = re.sub(r"(?m)^(\+.*)$", r'<span class="add">\1</span>', safe)
            safe = re.sub(r"(?m)^(-.*)$", r'<span class="del">\1</span>', safe)
        body = f"<details><summary>工具调用 / 输出</summary><pre>{safe}</pre></details>" if is_tool else f"<pre>{safe}</pre>"
        if is_thought:
            body = f"<details><summary>思考</summary>{body}</details>"
        rows.append(f'<article class="{html.escape(role)}"><header>{html.escape(_ROLE_LABELS.get(role, role))} · {html.escape(_local_time(item.get("created_at")))}</header>{body}</article>')
    usage_text = html.escape(_usage_text(usage))
    doc = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{html.escape(title)}</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}header{{color:#666;font-size:12px}}article{{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:.5rem 0}}.add{{color:#176b35;background:#e8f5eb}}.del{{color:#a21d24;background:#fdebed}}.user{{background:#f7f9ff}}.meta{{color:#555}}</style>
<h1>{html.escape(title)}</h1><p class="meta">导出时间：{datetime.now().strftime("%Y-%m-%d %H:%M")} · 模型：{html.escape(model or "未记录")} · 用量：{usage_text}</p>{''.join(rows)}</html>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    return path


class ConversationShareStore:
    """Self-hosted, revocable, expiring read-only conversation shares."""

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            from atlas.config import DATA_ROOT
            path = DATA_ROOT / "exports" / "shares.sqlite3"
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS conversation_shares (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, conversation_id TEXT NOT NULL,
                title TEXT NOT NULL, base_url TEXT NOT NULL, payload TEXT NOT NULL,
                password_salt TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT NOT NULL DEFAULT ''
            )""")

    def create(self, *, conversation_id: str, title: str, base_url: str,
               messages: list[dict[str, Any]], password: str = "", retention_days: int = 30) -> dict[str, Any]:
        self._prune_expired()
        base = _share_base_url(base_url)
        if not 1 <= int(retention_days) <= 365:
            raise ValueError("分享保留时间应为 1 到 365 天")
        token = secrets.token_urlsafe(32)
        share_id = secrets.token_hex(12)
        now = datetime.now(UTC)
        expires = now.timestamp() + int(retention_days) * 86400
        expires_at = datetime.fromtimestamp(expires, UTC).isoformat()
        salt = secrets.token_bytes(16) if password else b""
        password_hash = _password_digest(password, salt) if password else b""
        payload = json.dumps(messages, ensure_ascii=False, separators=(",", ":"))
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("INSERT INTO conversation_shares VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
                share_id, hashlib.sha256(token.encode()).hexdigest(), conversation_id,
                redact(title), base, payload, salt.hex(), password_hash.hex(), now.isoformat(), expires_at, "",
            ))
        return {"id": share_id, "url": f"{base}/api/shared/{quote(token)}", "expires_at": expires_at,
                "password_protected": bool(password)}

    def read(self, token: str, password: str = "", *, allow_locked: bool = False) -> dict[str, Any] | None:
        self._prune_expired()
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with closing(sqlite3.connect(self.path)) as db, db:
            row = db.execute("SELECT id,title,payload,password_salt,password_hash,expires_at,revoked_at,base_url FROM conversation_shares WHERE token_hash=?", (token_hash,)).fetchone()
        if row is None or row[6] or datetime.fromisoformat(row[5]) <= datetime.now(UTC):
            return None
        if row[4]:
            if allow_locked and not password:
                return {"id": row[0], "title": row[1], "messages": [], "expires_at": row[5], "password_protected": True, "base_url": row[7]}
            candidate = _password_digest(password, bytes.fromhex(row[3])).hex()
            if not hmac.compare_digest(candidate, str(row[4])):
                raise PermissionError("分享口令不正确")
        return {"id": row[0], "title": row[1], "messages": json.loads(row[2]), "expires_at": row[5], "password_protected": bool(row[4]), "base_url": row[7]}

    def list(self, *, conversation_id: str | None = None) -> list[dict[str, Any]]:
        self._prune_expired()
        query = "SELECT id,conversation_id,title,base_url,created_at,expires_at,revoked_at,password_hash FROM conversation_shares"
        args: tuple[Any, ...] = ()
        if conversation_id:
            query += " WHERE conversation_id=?"; args = (conversation_id,)
        query += " ORDER BY created_at DESC"
        with closing(sqlite3.connect(self.path)) as db, db:
            rows = db.execute(query, args).fetchall()
        return [{"id": r[0], "conversation_id": r[1], "title": r[2], "base_url": r[3], "created_at": r[4],
                 "expires_at": r[5], "revoked": bool(r[6]), "password_protected": bool(r[7])} for r in rows]

    def revoke(self, share_id: str) -> bool:
        with closing(sqlite3.connect(self.path)) as db, db:
            cursor = db.execute("UPDATE conversation_shares SET revoked_at=? WHERE id=? AND revoked_at=''", (datetime.now(UTC).isoformat(), share_id))
        return cursor.rowcount > 0

    def _prune_expired(self) -> None:
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("DELETE FROM conversation_shares WHERE expires_at<=?", (datetime.now(UTC).isoformat(),))


def share_page_url(url: str, token: str) -> str:
    return f"{_share_base_url(url)}/api/shared/{quote(token)}"


def shared_page_html(share_url: str, share: dict[str, Any]) -> str:
    title = html.escape(str(share["title"]))
    rows = []
    for message in share.get("messages", []):
        role = str(message.get("role") or "assistant")
        label = html.escape(_ROLE_LABELS.get(role, role))
        content = html.escape(redact(str(message.get("content") or "")))
        rows.append(f'<article class="{html.escape(role)}"><header>{label} · {html.escape(_local_time(message.get("created_at")))}</header><pre>{content}</pre></article>')
    records = "".join(rows)
    export_endpoint = json.dumps(share_url + "/export", ensure_ascii=False).replace("<", "\\u003c")
    import_url = "atlas://share/" + quote(str(share.get("token") or "")) + "?" + urlencode({"source": share_url})
    password_form = "" if not share.get("password_protected") else '''<form id="unlock"><label>分享口令 <input id="password" type="password" autocomplete="current-password" required></label><button>查看对话</button><span id="error" role="alert"></span></form>'''
    content_class = "" if not share.get("password_protected") else "hidden"
    return f'''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{title} · Atlas 分享</title>
<style>body{{font:15px/1.6 system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222}}header{{color:#666;font-size:12px}}article{{border:1px solid #ddd;border-radius:10px;padding:1rem;margin:1rem 0}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;margin:.5rem 0}}.user{{background:#f7f9ff}}.hidden{{display:none}}form{{display:flex;gap:.6rem;align-items:center;margin:2rem 0}}input,button{{padding:.6rem;border-radius:.4rem}}#error{{color:#a21d24}}</style>
<h1>{title}</h1><p>只读分享 · 到期时间：{html.escape(str(share.get('expires_at') or ''))}</p>{password_form}<section id="timeline" class="{content_class}">{records}</section>
<p><a href="{html.escape(import_url, quote=True)}">导入到 Atlas，创建本地新对话</a></p>
<script>const form=document.getElementById('unlock');if(form)form.addEventListener('submit',async e=>{{e.preventDefault();const r=await fetch({export_endpoint},{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify({{password:document.getElementById('password').value}})}});if(!r.ok){{document.getElementById('error').textContent='口令错误或分享已过期';return}}const d=await r.json();document.getElementById('timeline').innerHTML=d.messages.map(m=>`<article><header>${{String(m.role)}} · ${{String(m.created_at||'')}}</header><pre>${{String(m.content||'').replace(/[&<>]/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;'}}[c]))}}</pre></article>`).join('');document.getElementById('timeline').classList.remove('hidden');form.remove()}});</script></html>'''


def _share_base_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("自托管分享地址必须是无凭据、无查询参数的 HTTP(S) URL")
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def _password_digest(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
