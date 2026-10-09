"""自然语言提醒 → 既有 Automation（E8 主链路；**不另造 scheduler**）。

产品语义（00_任务书 §6 / S5、E8）：用户在聊天里说"明天上午 9 点提醒我交报告"
→ 模型调用 :func:`create_reminder`（模型工具 ``automation_manage``）→ **真实**
写入 ``data/automations.toml`` 并 ``engine.sync_automation`` 到既有
AutomationEngine 的 date 触发面。说"取消那个提醒"→ :func:`cancel_reminder`；
说"改到下午"→ :func:`update_reminder`。三者共用同一份 store/engine，不存在
第二套调度器。

提醒记录用**既有冻结字段**表达（不改 schema、不加枚举）：

  * ``trigger = {"kind": "date", "at": <ISO 8601>}`` —— 引擎 date 触发一次性到期；
  * ``payload = {"kind": "agent_turn", "message": <提醒正文>, "wake_mode": "now"}``；
  * ``name = "提醒：" + <提醒正文>`` —— **提醒类记录的可识别前缀**（store 会丢弃
    未登记的顶层字段，故用 name 前缀而不是新字段来标记，避免触碰 schema 红线）。

幂等与取消：取消 = **保留记录但 ``enabled=False``**（不删行）。这样
``GET /api/automations/{id}/runs`` 仍可读（返回空运行史），审计能区分"已取消"
与"从未创建"；同时引擎侧 ``sync_automation`` 会撤掉未 fire 的 date 调度。
引擎未启动（DBOS 未接线）时只写产品状态，sync 为 no-op —— 与
``/api/automations`` CRUD 的既有契约一致。
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from atlas.automation import get_automation_engine
from atlas.automation.store import (
    AutomationValidationError,
    normalize_source_binding,
    normalize_record,
    validate_record,
)
from atlas.time_context import attach_user_timezone, now_local

log = structlog.get_logger()

#: 提醒记录的可识别前缀（store 丢弃未登记字段，故不用新字段标记）
REMINDER_PREFIX = "提醒："


class ReminderError(ValueError):
    """提醒参数/解析错误（本地形状错误，先于 store 校验）。"""


_CN_NUMERALS = {
    "零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10, "十一": 11, "十二": 12,
}
_PERIODS = {"凌晨": 0, "早上": 0, "早晨": 0, "上午": 0, "中午": 12,
            "下午": 12, "傍晚": 12, "晚上": 12, "夜里": 12, "晚": 12}
_WEEKDAY = re.compile(r"(下周|下星期|本周|这周)([一二三四五六日天])")
_WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4,
                  "六": 5, "日": 6, "天": 6}


def _cn_hour(text: str) -> int | None:
    """中文/数字小时 → 0-23（"九"/"9"/"十二"）。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        value = int(text)
        return value if 0 <= value <= 23 else None
    if len(text) == 1 and text in _CN_NUMERALS:
        value = _CN_NUMERALS[text]
        return value if 0 <= value <= 23 else None
    if text in _CN_NUMERALS:
        value = _CN_NUMERALS[text]
        return value if 0 <= value <= 23 else None
    if text.startswith("十"):
        rest = text[1:]
        return 10 + (_CN_NUMERALS.get(rest, 0) if rest else 0)
    if text.endswith("十"):
        head = text[:-1]
        return _CN_NUMERALS.get(head, 1) * 10
    return None


def parse_due(text: str, *, now: datetime, config: Any = None) -> datetime:
    """把相对时间短语解析为绝对时间（"明天上午 9 点" / "今天下午3点" / ISO）。

    只支持**明确可换算**的形式；含糊说法（"晚点"/"回头"）→ ReminderError，
    绝不猜（猜出来的提醒是假承诺）。ISO 8601 直接透传。
    """
    raw = str(text or "").strip()
    if not raw:
        raise ReminderError("提醒时间不能为空")
    reference = now_local(config, now=now)
    # ISO 8601 直通（含 "2026-10-05 09:00"）
    for candidate in (raw, raw.replace(" ", "T", 1)):
        try:
            return attach_user_timezone(datetime.fromisoformat(candidate), config)
        except ValueError:
            pass

    # ISO 时间戳前缀（"2026-10-05 09:00:00 提醒我..."）
    match = re.match(
        r"^(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})"
        r"(?::(\d{2}))?(Z|[+-]\d{2}:?\d{2})?", raw,
    )
    if match:
        offset = match.group(5) or ""
        if offset == "Z":
            offset = "+00:00"
        value = datetime.fromisoformat(
            f"{match.group(1)}T{int(match.group(2)):02d}:{match.group(3)}:"
            f"{match.group(4) or '00'}{offset}"
        )
        return attach_user_timezone(value, config)

    day_offset: int | None = None
    weekday = _WEEKDAY.search(raw)
    if weekday:
        week_start = reference.date() - timedelta(days=reference.weekday())
        target = week_start + timedelta(
            days=_WEEKDAY_INDEX[weekday.group(2)] +
            (7 if weekday.group(1) in ("下周", "下星期") else 0))
        day_offset = (target - reference.date()).days
    elif "大后天" in raw:
        day_offset = 3
    elif "后天" in raw:
        day_offset = 2
    elif "明天" in raw or "明日" in raw:
        day_offset = 1
    elif "今天" in raw or "今日" in raw or "今晚" in raw:
        day_offset = 0

    period = 0
    period_match = None
    for token, offset in _PERIODS.items():
        index = raw.find(token)
        if index >= 0 and (period_match is None or index < period_match[0]):
            period_match = (index, token, offset)
    if period_match is not None:
        period = period_match[2]

    hour = minute = None
    colon = re.search(r"(\d{1,2})\s*[：:]\s*(\d{1,2})", raw)
    if colon:
        hour, minute = int(colon.group(1)), int(colon.group(2))
    else:
        point = re.search(r"(\d{1,2}|[零〇一二两三四五六七八九十]+)\s*点(半|一刻|三刻|"
                          r"[零〇一二两三四五六七八九十]+分)?", raw)
        if point:
            hour = _cn_hour(point.group(1))
            tail = point.group(2) or ""
            if tail == "半":
                minute = 30
            elif tail == "一刻":
                minute = 15
            elif tail == "三刻":
                minute = 45
            elif tail.endswith("分"):
                minute = _cn_hour(tail[:-1]) or 0
            else:
                minute = 0

    if hour is None:
        # 只有日期没有钟点 → 默认 09:00（提醒的常见默认），且必须能定位到某一天
        if day_offset is None:
            raise ReminderError(f"无法从 {text!r} 解析出提醒时间（需要日期或钟点）")
        hour, minute = 9, 0

    if period and hour < 12:
        hour = (hour % 12) + period if period == 12 else hour
    if hour == 12 and period == 0 and period_match is not None:
        hour = 0  # "凌晨12点" → 00:00
    if not 0 <= int(hour) <= 23 or not 0 <= int(minute or 0) <= 59:
        raise ReminderError(f"提醒时间非法: {text!r}")

    base = reference.replace(hour=int(hour), minute=int(minute or 0), second=0, microsecond=0)
    if day_offset is not None:
        base = base + timedelta(days=day_offset)
    elif base <= reference:
        # 只说钟点且已过 → 明天同一钟点（最常见的口语意图）
        base = base + timedelta(days=1)
    try:
        return attach_user_timezone(base.replace(tzinfo=None), config)
    except ValueError as exc:
        raise ReminderError(str(exc)) from exc


#: 提醒正文的口语噪声前缀（去重比较前剥离："提醒我交报告" ≡ "交报告"）
_PREFIX_NOISE = ("提醒我一下", "提醒我", "提醒一下", "提醒", "记得", "别忘了", "别忘记")


def _core_text(text: str) -> str:
    """提醒正文归一化：去标点 + 剥口语前缀（只用于**去重比较**，不改存储内容）。"""
    normalized = re.sub(r"[\s，。,.!！?？:：;；、~～]+", "", str(text or ""))
    changed = True
    while changed:
        changed = False
        for noise in _PREFIX_NOISE:
            if normalized.startswith(noise) and len(normalized) > len(noise):
                normalized = normalized[len(noise):]
                changed = True
    return normalized


def _same_reminder(left: str, right: str) -> bool:
    """两条提醒正文是否指同一件事（相等或互相包含；空文本永不判同）。"""
    a, b = _core_text(left), _core_text(right)
    if not a or not b:
        return False
    return a == b or a in b or b in a


def _same_action(left: str, right: str) -> bool:
    """Conservative action match for source-bound tool/pipeline convergence.

    Require an exact normalized action after a small set of explicit Chinese
    verb normalizations. Similarity based on character bigrams can be dominated
    by shared identifiers or suffixes and merge different actions from one
    source message.
    """
    a, b = _core_text(left), _core_text(right)
    if not a or not b:
        return False

    def canonical_action(value: str) -> str:
        # These common verb forms preserve the same object and intent while
        # avoiding fuzzy matching across different actions sharing a suffix.
        return value.replace("提交", "交").replace("发送", "发")

    return canonical_action(a) == canonical_action(b)


def _same_due(left: Any, right: Any) -> bool:
    try:
        a = datetime.fromisoformat(str(left).replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(right).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if a.tzinfo is None or b.tzinfo is None:
        return False
    return a.astimezone(UTC) == b.astimezone(UTC)


def resolve_update_due(*, due_at: str = "", due_text: str = "",
                       now: datetime | None = None, config: Any = None) -> str:
    """Purely resolve and validate a future update due before any side effect."""
    reference = now_local(config, now=now)
    raw = str(due_at or "").strip()
    if raw:
        try:
            due = attach_user_timezone(
                datetime.fromisoformat(raw.replace(" ", "T", 1)), config)
        except ValueError as exc:
            raise ReminderError(f"due_at 非法 ISO 时间: {raw!r}") from exc
    else:
        due = parse_due(due_text, now=reference, config=config)
    if due.astimezone(UTC) <= reference.astimezone(UTC):
        raise ReminderError("改期必须晚于当前时间")
    return due.isoformat()


def _engine(engine: Any = None) -> Any:
    return engine if engine is not None else get_automation_engine()


async def _cancel_active_runs(engine: Any, automation_id: str) -> list[str]:
    """撤掉活跃 run/interval loop —— 引擎未启动时 no-op（``engine.cancel`` 会
    ``_require_started()`` 抛错，取消产品状态不应因此失败）。"""
    if not getattr(engine, "started", False):
        return []
    try:
        result = await engine.cancel(automation_id)
    except Exception:  # noqa: BLE001 — 引擎侧取消失败不掩盖产品状态已停用
        log.exception("memory.reminder_cancel_runs_failed", automation_id=automation_id)
        return []
    return list((result or {}).get("cancelled") or [])


def _reminders(store: Any) -> list[dict[str, Any]]:
    return [record for record in store.list()
            if str(record.get("name") or "").startswith(REMINDER_PREFIX)]


def _message_of(record: dict[str, Any]) -> str:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    text = str(payload.get("message") or "")
    if text:
        return text
    return str(record.get("name") or "")[len(REMINDER_PREFIX):]


# 取消/改期时模型常把整句回述过来（"取消明天上午交报告的那个提醒"）——
# 先剥命令噪音再匹配，避免"整句不是子串"导致取消失败。
_QUERY_NOISE = (
    "取消", "删掉", "删除", "不用了", "不要了", "别再", "那个", "这个", "这条",
    "提醒我", "提醒", "一下", "帮我", "把", "的", "我", "了", "吧", "吗", "呢",
    "改到", "改成", "改为", "推迟到", "延到", "调成", "调为",
    "？", "?", "。", "，", ",", "！", "!", "：", ":",
)


def _query_core(query: str) -> str:
    text = str(query or "").strip()
    for word in _QUERY_NOISE:
        text = text.replace(word, "")
    return text.strip()


def _bigram_overlap(left: str, right: str) -> float:
    if len(left) < 2 or len(right) < 2:
        return 0.0
    left_grams = {left[i:i + 2] for i in range(len(left) - 1)}
    right_grams = {right[i:i + 2] for i in range(len(right) - 1)}
    if not left_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams)


def _match(record: dict[str, Any], query: str) -> bool:
    """取消/更新时的匹配：query 为空 → 最近的提醒；否则逐级放宽。

    1. 原样子串（最严格）；
    2. 剥噪音后的核心子串（"取消明天上午交报告的那个提醒" → "明天上午交报告"）；
    3. 反向包含（记录正文出现在 query 里）；
    4. 二元组重合 ≥ 0.6（中文短句容错，不误伤"周报" vs "报告"）。
    """
    query = str(query or "").strip()
    if not query:
        return True
    message = _message_of(record)
    haystack = " ".join([
        message, str(record.get("name") or ""),
        str((record.get("trigger") or {}).get("at") or ""),
    ])
    if query in haystack:
        return True
    core = _query_core(query)
    if core and core in haystack:
        return True
    if message and message in query:
        return True
    return _bigram_overlap(core or query, message) >= 0.6


def _sorted_reminders(store: Any) -> list[dict[str, Any]]:
    items = _reminders(store)
    items.sort(key=lambda record: str(record.get("created_at") or ""), reverse=True)
    return items


def find_reminder(*, query: str = "", automation_id: str = "",
                  include_disabled: bool = False, engine: Any = None
                  ) -> dict[str, Any] | None:
    """Resolve one reminder using the same target rules as cancel/update."""
    store = _engine(engine).store
    if automation_id:
        target = store.get(str(automation_id))
        if target is not None and str(target.get("name") or "").startswith(REMINDER_PREFIX):
            if include_disabled or target.get("enabled") is not False:
                return target
        return None
    candidates = [record for record in _sorted_reminders(store)
                  if (include_disabled or record.get("enabled") is not False)
                  and _match(record, query)]
    return candidates[0] if len(candidates) == 1 else None


async def create_reminder(*, message: str, due_at: str = "", due_text: str = "",
                          name: str = "", automation_id: str = "",
                          source_binding: dict[str, Any] | None = None,
                          now: datetime | None = None, context: str = "",
                          engine: Any = None, config: Any = None) -> dict[str, Any]:
    """创建提醒：真实写 store + ``engine.sync_automation``（E8）。"""
    text = str(message or "").strip()
    if not text:
        raise ReminderError("提醒内容不能为空")
    reference = now_local(config, now=now)
    due_iso = str(due_at or "").strip()
    if due_iso:
        try:
            due = attach_user_timezone(
                datetime.fromisoformat(due_iso.replace(" ", "T", 1)), config)
        except ValueError as exc:
            raise ReminderError(f"due_at 非法 ISO 时间: {due_iso!r}") from exc
    else:
        due = parse_due(due_text, now=reference, config=config)

    automation_engine = _engine(engine)
    store = automation_engine.store
    binding = normalize_source_binding(source_binding)

    due_iso_norm = due.isoformat()
    records = store.list()
    if binding.get("request_run_id"):
        # Cross-path convergence is scoped to the actual Atlas run, same due
        # instant, and one unambiguous action match. It never merges unrelated
        # messages globally or collapses two actions from one message.
        matches = [record for record in records
                   if str(record.get("name") or "").startswith(REMINDER_PREFIX)
                   and str((record.get("source_binding") or {}).get("request_run_id") or "")
                   == binding["request_run_id"]
                   and _same_due((record.get("trigger") or {}).get("at"), due_iso_norm)
                   and _same_action(_message_of(record), text)]
        if len(matches) == 1:
            matched = dict(matches[0])
            old_binding = matched.get("source_binding") or {}
            matched["source_binding"] = {**old_binding, **binding}
            if matched.get("enabled") is False:
                saved = store.put(normalize_record(matched))
                return {"created": False, "deduped": False,
                        "reason": "source_reminder_cancelled", "automation": saved,
                        "due_at": due_iso_norm, "context": context}
            saved = store.put(normalize_record(matched))
            await automation_engine.sync_automation(saved)
            log.info("memory.reminder_deduped", automation_id=saved.get("id"))
            return {"created": False, "deduped": True, "automation": saved,
                    "due_at": due_iso_norm, "context": context}
    else:
        # Legacy callers without source provenance retain the historical local
        # de-duplication behavior. Model/tool and observer paths always provide
        # the actual request_run_id.
        for record in records:
            if not str(record.get("name") or "").startswith(REMINDER_PREFIX):
                continue
            if record.get("enabled") is False:
                continue
            if not _same_reminder(_message_of(record), text):
                continue
            if str((record.get("trigger") or {}).get("at") or "") != due_iso_norm:
                continue
            log.info("memory.reminder_deduped", automation_id=record.get("id"))
            return {"created": False, "deduped": True, "automation": record,
                    "due_at": due_iso_norm, "context": context}

    existing_ids = {str(record.get("id") or "") for record in store.list()}
    if automation_id:
        new_id = str(automation_id)
        existing = store.get(new_id)
        if existing is not None and existing.get("enabled") is False:
            return {"created": False, "deduped": False,
                    "reason": "automation_cancelled", "automation": existing,
                    "due_at": str((existing.get("trigger") or {}).get("at") or ""),
                    "context": context}
        if existing is not None and binding:
            if (_same_due((existing.get("trigger") or {}).get("at"), due_iso_norm)
                    and _same_action(_message_of(existing), text)):
                saved = store.put(normalize_record({
                    **existing,
                    "source_binding": {
                        **(existing.get("source_binding") or {}), **binding,
                    },
                }))
                await automation_engine.sync_automation(saved)
                return {"created": False, "deduped": True, "automation": saved,
                        "due_at": due_iso_norm, "context": context}
            return {"created": False, "deduped": False,
                    "reason": "automation_id_conflict", "automation": existing,
                    "due_at": str((existing.get("trigger") or {}).get("at") or ""),
                    "context": context}
    else:
        for _ in range(20):
            new_id = "rem-" + uuid.uuid4().hex[:12]
            if new_id not in existing_ids:
                break
        else:  # pragma: no cover - 概率上不可达
            raise ReminderError("无法生成唯一 reminder id")

    record = normalize_record({
        "id": new_id,
        "name": (str(name).strip() or REMINDER_PREFIX + text),
        "enabled": True,
        "trigger": {"kind": "date", "at": due.isoformat()},
        "payload": {"kind": "agent_turn", "message": text, "wake_mode": "now"},
        "delivery": {"mode": "none"},
        "policy": {"missed_run": "skip", "delete_after_run": False},
        "created_at": reference.isoformat(),
        "updated_at": reference.isoformat(),
    })
    if binding:
        record["source_binding"] = binding
    if not str(record.get("name") or "").startswith(REMINDER_PREFIX):
        record["name"] = REMINDER_PREFIX + str(record.get("name") or text)
    validate_record(record)
    saved = store.put(record)
    await automation_engine.sync_automation(saved)
    log.info("memory.reminder_created", automation_id=saved["id"], at=due.isoformat())
    return {"created": True, "automation": saved, "due_at": due.isoformat(),
            "context": context}


async def cancel_reminder(*, query: str = "", automation_id: str = "",
                          now: datetime | None = None, context: str = "",
                          engine: Any = None, config: Any = None) -> dict[str, Any]:
    """取消提醒：保留记录但 ``enabled=False`` + 引擎撤调度（可审计、可回查）。"""
    automation_engine = _engine(engine)
    store = automation_engine.store
    reference = now_local(config, now=now)
    target = find_reminder(query=query, automation_id=automation_id, engine=automation_engine)
    if target is None:
        return {"cancelled": False, "reason": "no_matching_reminder",
                "query": query, "context": context}

    updated = dict(target)
    updated["enabled"] = False
    updated["updated_at"] = reference.isoformat()
    saved = store.put(normalize_record(updated))
    cancelled_runs = await _cancel_active_runs(automation_engine, saved["id"])
    await automation_engine.sync_automation(saved)   # enabled=False → 撤 date 调度
    log.info("memory.reminder_cancelled", automation_id=saved["id"])
    return {"cancelled": True, "automation": saved, "message": _message_of(saved),
            "cancelled_runs": cancelled_runs, "context": context}


async def update_reminder(*, automation_id: str = "", query: str = "", due_at: str = "",
                          due_text: str = "", message: str = "", now: datetime | None = None,
                          source_binding: dict[str, Any] | None = None,
                          context: str = "", engine: Any = None,
                          config: Any = None) -> dict[str, Any]:
    """改期/改内容：同一记录原地更新 + 重新 sync（不新建第二条）。"""
    automation_engine = _engine(engine)
    store = automation_engine.store
    reference = now_local(config, now=now)
    target = find_reminder(query=query, automation_id=automation_id,
                           include_disabled=True, engine=automation_engine)
    if target is None:
        return {"updated": False, "reason": "no_matching_reminder",
                "query": query, "context": context}

    updated = dict(target)
    if due_at or due_text:
        due_iso = resolve_update_due(due_at=due_at, due_text=due_text,
                                     now=reference, config=config)
        updated["trigger"] = {**(target.get("trigger") or {}), "kind": "date",
                              "at": due_iso}
    if message:
        updated["payload"] = {**(target.get("payload") or {}), "message": str(message)}
        updated["name"] = REMINDER_PREFIX + str(message)
    updated["enabled"] = True
    if source_binding is not None:
        updated["source_binding"] = normalize_source_binding(source_binding)
    updated["updated_at"] = reference.isoformat()
    saved = store.put(normalize_record(updated))
    await automation_engine.sync_automation(saved)
    log.info("memory.reminder_updated", automation_id=saved["id"])
    return {"updated": True, "automation": saved, "due_at": (saved.get("trigger") or {}).get("at"),
            "context": context}


def list_reminders(*, context: str = "", engine: Any = None) -> dict[str, Any]:
    """列出提醒（含已取消），供"我明天还有什么待办提醒吗"回答与审计。"""
    store = _engine(engine).store
    items = _sorted_reminders(store)
    reminders = [
        {
            "id": record.get("id"),
            "message": _message_of(record),
            "at": (record.get("trigger") or {}).get("at"),
            "enabled": record.get("enabled"),
            "created_at": record.get("created_at"),
            "updated_at": record.get("updated_at"),
        }
        for record in items
    ]
    active = [item for item in reminders if item["enabled"] is not False]
    return {
        "reminders": reminders,
        # 已取消的提醒留在 store 里（可审计），回答"还有什么待办"只看 active，
        # 否则模型会把取消过的当成还在。
        "active_reminders": active,
        "active_count": len(active),
        "context": context,
    }


__all__ = [
    "REMINDER_PREFIX",
    "ReminderError",
    "find_reminder",
    "resolve_update_due",
    "parse_due",
    "create_reminder",
    "cancel_reminder",
    "update_reminder",
    "list_reminders",
    "AutomationValidationError",
]
