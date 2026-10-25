"""Short-lived, memory-only importer for user-exported Chromium password CSVs."""

from __future__ import annotations

import csv
import io
import secrets
import threading
import time
from urllib.parse import urlsplit

_LOCK = threading.Lock()
_SESSIONS: dict[str, tuple[float, list[dict[str, str]]]] = {}
_TTL_SECONDS = 15 * 60
_MAX_ROWS = 5000


def preview_csv(source: str, text: str) -> dict[str, object]:
    if len(text.encode("utf-8")) > 8 * 1024 * 1024:
        raise ValueError("密码 CSV 超过 8 MiB")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = {str(name or "").strip().lower(): name for name in (reader.fieldnames or [])}
    for required in ("url", "username", "password"):
        if required not in headers:
            raise ValueError("CSV 必须包含 Chrome/Edge 导出的 url、username、password 列")
    rows = []
    candidates = []
    for index, row in enumerate(reader):
        if index >= _MAX_ROWS:
            raise ValueError("一次最多预览 5000 条密码记录")
        url = (row.get(headers["url"]) or "").strip()
        username = (row.get(headers["username"]) or "").strip()
        password = row.get(headers["password"]) or ""
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username or parts.password or not username or not password):
            continue
        origin = f"{parts.scheme}://{parts.netloc}"
        candidate_id = secrets.token_urlsafe(18)
        name_key = headers.get("name")
        label = (row.get(name_key) or parts.hostname).strip() if name_key else parts.hostname
        rows.append({"id": candidate_id, "origin": origin, "username": username,
                     "password": password, "label": label, "source": source[:120]})
        candidates.append({"id": candidate_id, "origin": origin, "username": username,
                           "label": label, "source": source[:120]})
    token = secrets.token_urlsafe(32)
    with _LOCK:
        now = time.monotonic()
        for key, (expiry, _) in list(_SESSIONS.items()):
            if expiry <= now:
                del _SESSIONS[key]
        if len(_SESSIONS) >= 8:
            oldest = min(_SESSIONS, key=lambda key: _SESSIONS[key][0])
            del _SESSIONS[oldest]
        _SESSIONS[token] = (now + _TTL_SECONDS, rows)
    return {"import_token": token, "candidates": candidates}


def import_selected(token: str, selected_ids: list[str], store: object, *, overwrite_confirmed: bool) -> dict[str, list[str]]:
    with _LOCK:
        entry = _SESSIONS.get(token)
        if entry is None or entry[0] <= time.monotonic():
            _SESSIONS.pop(token, None)
            raise ValueError("导入预览已过期，请重新选择 CSV")
        rows = entry[1]
    wanted = set(selected_ids)
    items = store.list_items()  # type: ignore[attr-defined]
    existing = {}
    for meta in items:
        data = meta.to_dict() if hasattr(meta, "to_dict") else meta
        if data.get("kind") == "login" and data.get("origin"):
            existing[f"{data['origin']}\0{data.get('identifier') or ''}"] = str(data.get("id") or "")
    imported: list[str] = []
    skipped: list[str] = []
    for item in rows:
        if item["id"] not in wanted:
            continue
        key = f"{item['origin']}\0{item['username']}"
        if key in existing:
            if not overwrite_confirmed or not store.rotate_login_password(existing[key], item["password"]):  # type: ignore[attr-defined]
                skipped.append(item["id"])
                continue
        else:
            meta = store.add_item(  # type: ignore[attr-defined]
                "login", item["label"],
                {"identifier_type": "username", "identifier": item["username"], "password": item["password"]},
                item["origin"],
                login_method={"fields": {"identifier": "username", "password": "current-password"},
                              "confirm_before_fill": True, "source": item["source"]},
            )
            existing[key] = meta.id
        imported.append(item["id"])
    with _LOCK:
        _SESSIONS.pop(token, None)
    return {"imported": imported, "skipped": skipped}
