"""MemOS 记忆变动追踪。

MemOS 自己的事件流不记录删除（``POST /api/v1/traces/delete`` 不留事件 / 审计），
所以这里不依赖它：定期对 MemOS 本地库（``<MEMOS_HOME>/data/memos.db``，只读打开）
做快照对比，记录每一次新增 / 删除 / 修改，以及改动前后的字段内容；再从 MemOS 的
``logs/events.jsonl`` 里找出同一对象附近的事件，作为"变动原因"（技能结晶、策略修订……）。

变动记录存在 Atlas 自己的 ``<DATA_ROOT>/data/memory_changes.sqlite3``，不写 MemOS 的库。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import structlog

from atlas.config import DATA_ROOT

log = structlog.get_logger()

# 被跟踪的 MemOS 表 → 中文名、标题字段、只算"评分变化"的数值字段。
ENTITIES: dict[str, dict[str, Any]] = {
    "user_facts": {"label": "关于你", "title": ("text",), "score": set()},
    "traces": {"label": "对话记录", "title": ("summary", "user_text"),
               "score": {"value", "priority", "alpha", "r_human"}},
    "episodes": {"label": "情节", "title": ("id",), "score": {"r_task"}},
    "policies": {"label": "策略", "title": ("title",), "score": {"support", "gain"}},
    "world_model": {"label": "世界模型", "title": ("title",), "score": set()},
    "skills": {"label": "技能", "title": ("name", "invocation_guide"),
               "score": {"eta", "support", "gain", "trials_attempted", "trials_passed"}},
    "feedback": {"label": "反馈", "title": ("polarity", "channel"), "score": set()},
}
# 不进入对比的列：向量、归属、内部版本、纯时间戳。
_SKIP_COLS = {"vec", "vec_summary", "vec_action", "schema_version", "owner_agent_kind",
              "owner_profile_id", "owner_workspace_id", "updated_at", "last_seen_at"}

OP_LABELS = {"added": "新增", "removed": "删除", "updated": "修改", "scored": "评分变化",
             "decayed": "淡忘", "archived": "归档"}

FIELD_LABELS = {
    "user_text": "用户说", "agent_text": "Atlas 回答", "summary": "摘要", "reflection": "反思",
    "tool_calls_json": "工具调用", "value": "价值", "priority": "优先级", "alpha": "反思权重",
    "r_human": "人类反馈分", "status": "状态", "r_task": "任务得分", "trace_ids_json": "包含的记录",
    "ended_at": "结束时间", "started_at": "开始时间", "title": "标题", "trigger": "触发条件",
    "procedure": "做法", "verification": "验证方式", "boundary": "适用边界", "support": "支持次数",
    "gain": "收益", "body": "内容", "policy_ids_json": "来源策略", "name": "名称",
    "invocation_guide": "使用说明", "procedure_json": "步骤", "eta": "采用率",
    "trials_attempted": "试用次数", "trials_passed": "试用通过", "source_policies_json": "来源策略",
    "source_world_json": "来源世界模型", "channel": "渠道", "polarity": "正负", "magnitude": "强度",
    "ts": "时间", "episode_id": "情节", "session_id": "会话", "meta_json": "附加信息",
    "source_episodes_json": "来源情节", "induced_by": "生成方式", "created_at": "创建时间",
}

POLL_SECONDS = 15.0
_lock = threading.Lock()
_watcher_started = False


def memos_home() -> Path:
    return Path(os.environ.get("MEMOS_HOME") or (DATA_ROOT / "data" / "memos-home"))


def memos_db_path() -> Path:
    return memos_home() / "data" / "memos.db"


def store_path() -> Path:
    (DATA_ROOT / "data").mkdir(parents=True, exist_ok=True)
    return DATA_ROOT / "data" / "memory_changes.sqlite3"


def _store() -> sqlite3.Connection:
    conn = sqlite3.connect(store_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS snapshot (entity TEXT, id TEXT, fp TEXT, data_json TEXT,
                                             PRIMARY KEY (entity, id));
        CREATE TABLE IF NOT EXISTS changes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL,
            entity TEXT, entity_id TEXT, op TEXT, title TEXT, fields_json TEXT,
            before_json TEXT, after_json TEXT, reason TEXT);
        CREATE INDEX IF NOT EXISTS changes_ts ON changes (ts);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """
    )
    return conn


def _short(value: Any, limit: int = 2000) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


def _read_memos() -> dict[str, dict[str, dict[str, Any]]] | None:
    db = memos_db_path()
    if not db.exists():
        return None
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        out: dict[str, dict[str, dict[str, Any]]] = {}
        for table in ENTITIES:
            if table not in tables:
                continue
            cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')
                    if r[1] not in _SKIP_COLS and (r[2] or "").upper() != "BLOB"]
            if "id" not in cols:
                continue
            col_sql = ", ".join(f'"{c}"' for c in cols)
            out[table] = {str(row["id"]): {c: _short(row[c]) for c in cols}
                          for row in conn.execute(f'SELECT {col_sql} FROM "{table}"')}
        return out
    finally:
        conn.close()


def _fingerprint(data: dict[str, Any]) -> str:
    return hashlib.sha1(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                   default=str).encode("utf-8")).hexdigest()


def _title(entity: str, data: dict[str, Any]) -> str:
    for key in ENTITIES[entity]["title"]:
        value = data.get(key)
        if value not in (None, ""):
            return str(value).replace("\n", " ")[:120]
    return str(data.get("id", ""))


def _classify(entity: str, before: dict[str, Any], after: dict[str, Any],
              fields: list[str]) -> str:
    if "status" in fields and str(after.get("status", "")).lower() in {"retired", "archived"}:
        return "archived"
    score_fields = ENTITIES[entity]["score"]
    if fields and all(f in score_fields for f in fields):
        if fields == ["priority"] or set(fields) <= {"priority", "value"}:
            try:
                if float(after.get("priority") or 0) < float(before.get("priority") or 0):
                    return "decayed"
            except (TypeError, ValueError):
                pass
        return "scored"
    return "updated"


def _epoch(value: Any) -> float:
    """MemOS timestamps are ms epochs (events) or ISO strings (log records)."""
    try:
        number = float(value)
        return number / 1000.0 if number > 1e11 else number
    except (TypeError, ValueError):
        pass
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _load_events(conn: sqlite3.Connection) -> list[tuple[float, str, str]]:
    """Read new lines of MemOS logs/events.jsonl since the stored offset (best-effort)."""
    path = memos_home() / "logs" / "events.jsonl"
    if not path.exists():
        return []
    row = conn.execute("SELECT value FROM meta WHERE key='events_offset'").fetchone()
    offset = int(row["value"]) if row else 0
    size = path.stat().st_size
    if size < offset:  # rotated
        offset = 0
    events: list[tuple[float, str, str]] = []
    with path.open("rb") as fh:
        fh.seek(offset)
        for raw in fh:
            try:
                rec = json.loads(raw.decode("utf-8", errors="replace"))
            except ValueError:
                continue
            evt = rec.get("event") if isinstance(rec.get("event"), dict) else rec
            etype = str(evt.get("type") or rec.get("msg") or "")
            events.append((_epoch(evt.get("ts") or rec.get("ts")), etype,
                           json.dumps(evt, ensure_ascii=False, default=str)))
        new_offset = fh.tell()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('events_offset', ?)", (str(new_offset),))
    return events


EVENT_LABELS = {
    "trace.created": "记录了新的对话", "trace.value_updated": "记录价值更新",
    "trace.priority_decayed": "记录优先级衰减（淡忘）", "l2.candidate_added": "加入策略候选",
    "l2.induced": "归纳出新策略", "l2.revised": "策略被修订", "l2.boundary_shrunk": "策略适用范围收窄",
    "l3.abstracted": "抽象出世界模型", "l3.revised": "世界模型被修订",
    "feedback.received": "收到反馈", "reward.computed": "计算了任务得分",
    "skill.crystallized": "结晶出技能", "skill.eta_updated": "技能采用率更新",
    "skill.boundary_updated": "技能适用范围更新", "skill.archived": "技能被归档",
    "skill.repaired": "技能被修复", "decision_repair.generated": "生成决策修正",
}


def _reason(entity_id: str, ts: float, events: list[tuple[float, str, str]]) -> str:
    hits = [etype for ets, etype, body in events if entity_id in body and abs(ets - ts) < 600]
    labels = []
    for etype in hits:
        label = EVENT_LABELS.get(etype)
        if label and label not in labels:
            labels.append(label)
    return "、".join(labels)


def scan() -> int:
    """Compare MemOS against the last snapshot and record differences. Returns #changes."""
    with _lock:
        current = _read_memos()
        if current is None:
            return 0
        conn = _store()
        try:
            now = time.time()
            events = _load_events(conn)
            recorded = 0
            for entity, rows in current.items():
                old = {r["id"]: (r["fp"], json.loads(r["data_json"]))
                       for r in conn.execute("SELECT id, fp, data_json FROM snapshot WHERE entity=?", (entity,))}
                for eid, data in rows.items():
                    fp = _fingerprint(data)
                    if eid not in old:
                        conn.execute(
                            "INSERT INTO changes (ts, entity, entity_id, op, title, fields_json, before_json, after_json, reason)"
                            " VALUES (?,?,?,?,?,?,?,?,?)",
                            (now, entity, eid, "added", _title(entity, data), json.dumps(sorted(data)),
                             None, json.dumps(data, ensure_ascii=False, default=str), _reason(eid, now, events)))
                        recorded += 1
                    elif old[eid][0] != fp:
                        before = old[eid][1]
                        fields = sorted(k for k in set(before) | set(data) if before.get(k) != data.get(k))
                        conn.execute(
                            "INSERT INTO changes (ts, entity, entity_id, op, title, fields_json, before_json, after_json, reason)"
                            " VALUES (?,?,?,?,?,?,?,?,?)",
                            (now, entity, eid, _classify(entity, before, data, fields), _title(entity, data),
                             json.dumps(fields), json.dumps({k: before.get(k) for k in fields}, ensure_ascii=False, default=str),
                             json.dumps({k: data.get(k) for k in fields}, ensure_ascii=False, default=str),
                             _reason(eid, now, events)))
                        recorded += 1
                    conn.execute("INSERT OR REPLACE INTO snapshot (entity, id, fp, data_json) VALUES (?,?,?,?)",
                                 (entity, eid, fp, json.dumps(data, ensure_ascii=False, default=str)))
                for eid in set(old) - set(rows):
                    before = old[eid][1]
                    conn.execute(
                        "INSERT INTO changes (ts, entity, entity_id, op, title, fields_json, before_json, after_json, reason)"
                        " VALUES (?,?,?,?,?,?,?,?,?)",
                        (now, entity, eid, "removed", _title(entity, before), json.dumps(sorted(before)),
                         json.dumps(before, ensure_ascii=False, default=str), None, _reason(eid, now, events)))
                    conn.execute("DELETE FROM snapshot WHERE entity=? AND id=?", (entity, eid))
                    recorded += 1
            conn.commit()
            return recorded
        finally:
            conn.close()


def list_changes(*, limit: int = 100, before_id: int | None = None, entity: str = "",
                 op: str = "") -> dict[str, Any]:
    conn = _store()
    try:
        where, args = [], []
        if before_id:
            where.append("id < ?"); args.append(before_id)
        if entity:
            where.append("entity = ?"); args.append(entity)
        if op:
            where.append("op = ?"); args.append(op)
        sql = "SELECT * FROM changes" + (" WHERE " + " AND ".join(where) if where else "")
        rows = conn.execute(sql + " ORDER BY id DESC LIMIT ?", (*args, max(1, min(limit, 500)))).fetchall()
        stats = {r["op"]: r["n"] for r in conn.execute("SELECT op, COUNT(*) AS n FROM changes GROUP BY op")}
        items = []
        for r in rows:
            fields = json.loads(r["fields_json"] or "[]")
            items.append({
                "id": r["id"],
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(r["ts"])),
                "entity": r["entity"], "entity_label": ENTITIES.get(r["entity"], {}).get("label", r["entity"]),
                "entity_id": r["entity_id"], "op": r["op"], "op_label": OP_LABELS.get(r["op"], r["op"]),
                "title": r["title"], "reason": r["reason"] or "",
                "fields": [{"key": f, "label": FIELD_LABELS.get(f, f)} for f in fields],
                "before": json.loads(r["before_json"]) if r["before_json"] else None,
                "after": json.loads(r["after_json"]) if r["after_json"] else None,
            })
        return {"items": items, "next_before": items[-1]["id"] if len(items) == limit and items else None,
                "stats": stats, "memos_db": memos_db_path().exists()}
    finally:
        conn.close()


def ensure_watcher() -> None:
    """Start the background poller once per process (daemon thread)."""
    global _watcher_started
    if _watcher_started:
        return
    _watcher_started = True

    def loop() -> None:
        while True:
            try:
                scan()
            except Exception as exc:  # noqa: BLE001 — a bad scan must never kill the watcher
                log.debug("memos_changes.loop_failed", error=str(exc), exc_info=True)
            time.sleep(POLL_SECONDS)

    threading.Thread(target=loop, name="memos-change-watcher", daemon=True).start()
