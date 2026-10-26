"""Local APIs for Atlas U4 interface features."""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.config import get_config

router = APIRouter()


def _path() -> Path:
    return Path(get_config().db_path).parent / "u4-data.json"


def _read() -> dict[str, Any]:
    path = _path()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(value: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


_NOTIFICATION_LEVELS = ("attention", "all", "off")


def create_settings_proposal(*, key: str, old_value: Any, new_value: Any, reason: str = "", conversation_id: str = "") -> dict[str, Any]:
    if key not in {"model", "notifications.level", "advisor_model"}:
        raise ValueError("暂只支持模型、通知级别和顾问模型设置")
    if key == "notifications.level" and new_value not in _NOTIFICATION_LEVELS:
        raise ValueError(f"通知级别只能是 {', '.join(_NOTIFICATION_LEVELS)}（attention=只在需要我时，all=全部，off=关闭），收到 {new_value!r}")
    proposal = {"id": uuid.uuid4().hex, "key": key, "from": old_value, "to": new_value,
                "reason": reason[:500], "conversation_id": conversation_id,
                "created_at": datetime.now(UTC).isoformat(), "status": "pending"}
    data = _read()
    data.setdefault("proposals", []).append(proposal)
    _write(data)
    return proposal


@router.get("/api/u4/settings")
async def get_u4_settings(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    return _read().get("settings", {})


@router.put("/api/u4/settings")
async def put_u4_settings(body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    allowed = {"advisor_model", "mobile_push", "appearance", "language"}
    data = _read()
    settings = data.setdefault("settings", {})
    if "advisor_model" in body:
        advisor_model = str(body.get("advisor_model") or "").strip()
        if advisor_model:
            model_mgr = services.model_mgr
            if model_mgr is None:
                from atlas import server
                model_mgr = server.model_mgr
            if model_mgr is None or not any(item.get("id") == advisor_model for item in model_mgr.list_models()):
                raise HTTPException(status_code=422, detail="顾问模型必须来自已配置模型列表")
        body["advisor_model"] = advisor_model
    if "mobile_push" in body:
        push = body["mobile_push"]
        if not isinstance(push, dict) or not isinstance(push.get("events", {}), dict):
            raise HTTPException(status_code=422, detail="手机推送设置格式无效")
        push["enabled"] = bool(push.get("enabled"))
        push["channel"] = str(push.get("channel") or "telegram")[:40]
        push["chat_id"] = str(push.get("chat_id") or "")[:200]
        push["events"] = {name: bool((push.get("events") or {}).get(name)) for name in ("completion", "approval", "failure")}
    for key in allowed:
        if key in body:
            settings[key] = body[key]
    _write(data)
    return settings


@router.get("/api/u4/proposals")
async def get_proposals(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    return {"proposals": [item for item in _read().get("proposals", []) if item.get("status") == "pending"]}


@router.post("/api/u4/proposals")
async def create_proposal(body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    try:
        return create_settings_proposal(
            key=str(body.get("key") or "").strip(), old_value=body.get("from"),
            new_value=body.get("to"), reason=str(body.get("reason") or ""),
            conversation_id=str(body.get("conversation_id") or ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/api/u4/proposals/{proposal_id}/resolve")
async def resolve_proposal(proposal_id: str, body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    data = _read()
    proposals = data.setdefault("proposals", [])
    proposal = next((item for item in proposals if item.get("id") == proposal_id), None)
    if proposal is None or proposal.get("status") != "pending":
        raise HTTPException(status_code=404, detail="待确认设置提议不存在")
    if body.get("approve") is True:
        key, value = proposal["key"], proposal.get("to")
        settings = data.setdefault("settings", {})
        if key == "model":
            model_mgr = services.model_mgr
            if model_mgr is None:
                from atlas import server
                model_mgr = server.model_mgr
            try:
                model_mgr.select(str(value))
            except (ValueError, AttributeError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        elif key == "advisor_model":
            model_mgr = services.model_mgr
            if model_mgr is None:
                from atlas import server
                model_mgr = server.model_mgr
            if value and (model_mgr is None or not any(item.get("id") == value for item in model_mgr.list_models())):
                raise HTTPException(status_code=422, detail="顾问模型必须来自已配置模型列表")
            settings[key] = value
        else:
            settings[key] = value
        proposal["status"] = "approved"
    else:
        proposal["status"] = "rejected"
    proposal["resolved_at"] = datetime.now(UTC).isoformat()
    _write(data)
    return proposal


def _chatgpt_branch(mapping: dict[str, Any], current_node: Any) -> list[dict[str, Any]]:
    """Walk the export tree from current_node up to the root, so edited/regenerated
    branches the user abandoned are not mixed into the transcript."""
    nodes = {key: value for key, value in mapping.items() if isinstance(value, dict)}
    if isinstance(current_node, str) and current_node in nodes:
        chain, seen, cursor = [], set(), current_node
        while isinstance(cursor, str) and cursor in nodes and cursor not in seen:
            seen.add(cursor)
            chain.append(nodes[cursor])
            cursor = nodes[cursor].get("parent")
        return list(reversed(chain))
    # 旧格式/手工样例没有 current_node：按时间排序兜底，message 为 null 的根节点排最前。
    def created(node: dict[str, Any]) -> float:
        message = node.get("message") if isinstance(node.get("message"), dict) else {}
        return float(message.get("create_time") or 0)
    return sorted(nodes.values(), key=lambda node: (created(node), str(node.get("id") or "")))


def normalize_chatgpt_conversations(payload: Any) -> list[dict[str, Any]]:
    """Convert OpenAI's conversations.json mapping tree to plain role/content turns."""
    if isinstance(payload, dict):
        payload = payload.get("conversations") or [payload]
    if not isinstance(payload, list):
        raise ValueError("conversations.json 应是对话数组")
    result = []
    for conversation in payload:
        if not isinstance(conversation, dict):
            continue
        mapping = conversation.get("mapping")
        messages = []
        if isinstance(mapping, dict):
            for node in _chatgpt_branch(mapping, conversation.get("current_node")):
                message = node.get("message") if isinstance(node.get("message"), dict) else {}
                metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
                if metadata.get("is_visually_hidden_from_conversation"):
                    continue
                author = message.get("author") or {}
                role = author.get("role")
                content = message.get("content") or {}
                parts = content.get("parts", []) if isinstance(content, dict) else []
                text = "\n".join(str(part) for part in parts if isinstance(part, str)).strip()
                if role in {"user", "assistant"} and text:
                    messages.append({"role": role, "content": text})
        if messages:
            result.append({"title": str(conversation.get("title") or "ChatGPT 对话")[:120], "messages": messages,
                           "source_id": str(conversation.get("conversation_id") or conversation.get("id") or "")})
    return result


@router.post("/api/u4/import/chatgpt")
async def import_chatgpt(body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    memory = services.memory
    if memory is None:
        from atlas import server
        memory = server.memory
    try:
        conversations = normalize_chatgpt_conversations(body.get("conversations"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import append_session_message
    imported = []
    if memory is None:
        raise HTTPException(status_code=503, detail="会话服务尚未就绪")
    data = _read()
    seen_ids: dict[str, str] = data.setdefault("chatgpt_imported", {})
    skipped = 0
    for item in conversations:
        if item["source_id"] and item["source_id"] in seen_ids:
            skipped += 1
            continue
        conversation_id = await memory.create_conversation(f"ChatGPT · {item['title']}")
        for message in item["messages"]:
            await __import__("asyncio").to_thread(
                append_session_message, DATA_ROOT / "engine", conversation_id,
                message["role"], message["content"], {"external_source": "chatgpt"},
            )
        imported.append({"conversation_id": conversation_id, "title": item["title"], "messages": len(item["messages"])})
        if item["source_id"]:
            seen_ids[item["source_id"]] = conversation_id
            _write(data)
    return {"imported": len(imported), "skipped": skipped, "conversations": imported}


def _insights_cost_text(totals: dict[str, Any]) -> str:
    if totals.get("est_cost") is not None:
        return f"≈ {float(totals['est_cost']):.4f}"
    unpriced = int(totals.get("unpriced_records") or 0)
    known = float(totals.get("known_cost") or 0)
    if known > 0:
        return f"≈ {known:.4f}（另有 {unpriced} 条记录缺价格，未计入）"
    return "价格未知（该模型未配置价格，可在设置里填写）"


@router.get("/api/u4/insights")
async def get_insights(
    services: Annotated[AppServices, Depends(get_app_services)], days: int = 7,
    model: str | None = Query(default=None, max_length=256),
) -> dict[str, Any]:
    if days not in {7, 30}:
        raise HTTPException(status_code=422, detail="days must be 7 or 30")
    model = model.strip() if model and model.strip() else None
    today = datetime.now(UTC).date()
    start_date = today - timedelta(days=days - 1)
    end_date = today
    start = start_date.isoformat()
    end = (end_date + timedelta(days=1)).isoformat()
    ledger = services.usage_ledger
    usage = await ledger.query(start=start, end=end, group_by="model", model=model) if ledger else {"rows": [], "totals": {}}
    daily = await ledger.query(start=start, end=end, group_by="day", model=model) if ledger else {"rows": [], "totals": {}}
    all_models = await ledger.query(start=start, end=end, group_by="model") if ledger else {"rows": []}
    daily_by_date = {str(row.get("key")): row for row in daily.get("rows", [])}
    trends = []
    for offset in range(days):
        date_key = (start_date + timedelta(days=offset)).isoformat()
        row = daily_by_date.get(date_key)
        has_records = row is not None
        row = row or {}
        trends.append({
            "date": date_key, "runs": int(row.get("runs") or 0),
            "input_tokens": int(row.get("input_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or 0),
            "est_cost": row.get("est_cost") if has_records else 0.0,
            "known_cost": float(row.get("known_cost") or 0),
            "unpriced_records": int(row.get("unpriced_records") or 0),
        })
    trend_lines = []
    for row in trends:
        cost_label = f"≈ {row['est_cost']:.4f}" if row["est_cost"] is not None else f"缺价（{row['unpriced_records']} 条）"
        trend_lines.append(
            f"| {row['date']} | {row['runs']} | {row['input_tokens']} / {row['output_tokens']} | {cost_label} |"
        )
    memory = services.memory
    conversations = await memory.list_conversations(limit=None) if memory else []
    recent = [item for item in conversations if start <= str(item.get("updated_at") or "")[:10] <= end_date.isoformat()]
    task_types: dict[str, int] = {}
    tool_counts: dict[str, int] = {}
    errors = 0
    durations = []
    for conversation in recent[:200]:
        try:
            created = datetime.fromisoformat(str(conversation.get("created_at") or "").replace("Z", "+00:00"))
            updated = datetime.fromisoformat(str(conversation.get("updated_at") or "").replace("Z", "+00:00"))
            span = (updated - created).total_seconds()
            if span >= 0:
                durations.append(span)
        except (ValueError, TypeError):
            pass
        messages = await memory.get_conversation_messages(str(conversation.get("id") or ""), limit=100) if memory else []
        user_text = next((str(item.get("content") or "") for item in messages if item.get("role") == "user"), "")
        lowered = f"{conversation.get('title', '')} {user_text}".lower()
        task_type = next((name for terms, name in ((('bug', 'fix', '代码', '修复'), '编码'), (('write', '写', '文案', '邮件'), '写作'), (('search', 'research', '研究', '调研'), '研究'), (('?', '？', '解释', '什么'), '问答')) if any(term in lowered for term in terms)), "其他")
        task_types[task_type] = task_types.get(task_type, 0) + 1
        for message in messages:
            metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
            tool_name = metadata.get("tool_name") or metadata.get("name")
            if message.get("role") == "tool" and tool_name:
                tool_counts[str(tool_name)] = tool_counts.get(str(tool_name), 0) + 1
            if message.get("role") == "assistant" and any(term in str(message.get("content") or "").lower() for term in ("traceback", "failed", "error", "失败", "错误")):
                errors += 1
    totals = usage.get("totals", {})
    models = sorted(usage.get("rows", []), key=lambda row: int(row.get("runs") or 0), reverse=True)[:5]
    common_tasks = sorted(task_types.items(), key=lambda item: item[1], reverse=True)[:5]
    common_tools = sorted(tool_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    average_duration = int(sum(durations) / len(durations)) if durations else None
    markdown = "\n".join([
        f"# 最近 {days} 天使用习惯报告", "", f"- 统计范围：{start} 至 {end_date.isoformat()}（UTC，含首尾日期）",
        f"- 模型筛选：{model or '全部模型'}", f"- 会话数：{len(recent)}",
        f"- 平均会话跨度：{f'{average_duration // 3600} 小时 {average_duration % 3600 // 60} 分钟' if average_duration is not None else '未知'}（根据创建与最近更新时间估算）",
        f"- 模型调用：{totals.get('runs', 0)} 次", f"- 输入/输出：{totals.get('input_tokens', 0)} / {totals.get('output_tokens', 0)} tokens",
        f"- 缓存命中率：{format(totals['cache_hit_rate'], '.1%') if totals.get('cache_hit_rate') is not None else '未知'}",
        f"- 费用：{_insights_cost_text(totals)}（按本机模型价格估算 USD）", "",
        "## 每日调用与估算费用趋势", "| 日期（UTC） | 调用次数 | 输入/输出 Token | 估算费用（USD） |", "| --- | ---: | ---: | ---: |",
        *trend_lines,
        "", "## 常用模型", *[f"- {row.get('key')}: {row.get('runs', 0)} 次" for row in models],
        "", "## 常用任务类型", *[f"- {name}: {count} 个会话" for name, count in common_tasks],
        "", "## 常用工具", *([f"- {name}: {count} 次" for name, count in common_tools] or ["- 用量记录没有工具调用明细"]),
        "", f"## 出错情况\n检测到 {errors} 条包含错误线索的 Atlas 回复。",
        "", "## 建议", "- 检查高频任务是否适合保存为会话预设或配方。",
    ])
    from atlas.config import DATA_ROOT
    artifact_dir = DATA_ROOT / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    filename = f"insights-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S')}.md"
    (artifact_dir / filename).write_text(markdown + "\n", encoding="utf-8")
    return {
        "days": days, "start_date": start, "end_date": end_date.isoformat(),
        "model": model, "models": [row.get("key") for row in all_models.get("rows", [])],
        "trends": trends,
        "missing_price_records": sum(row["unpriced_records"] for row in trends),
        "markdown": markdown, "path": f"artifacts/{filename}",
        "conversation_count": len(recent), "usage": totals,
    }


@router.get("/api/u4/presets")
async def get_presets(services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    return {"presets": _read().get("presets", [])}


@router.post("/api/u4/presets")
async def save_preset(body: dict[str, Any], services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    label = str(body.get("label") or "").strip()
    if not label:
        raise HTTPException(status_code=422, detail="预设名称不能为空")
    preset = {key: body.get(key) for key in ("label", "workspace", "model", "reasoning_effort", "env", "skills")}
    workspace = str(preset.get("workspace") or "").strip()
    if workspace:
        if not Path(workspace).is_absolute():
            raise HTTPException(status_code=422, detail=f"工作目录必须是绝对路径：{workspace}")
        if not Path(workspace).is_dir():
            raise HTTPException(status_code=422, detail=f"工作目录不存在：{workspace}")
    preset["workspace"] = workspace
    preset.update({"id": str(body.get("id") or uuid.uuid4().hex), "updated_at": datetime.now(UTC).isoformat()})
    data = _read()
    presets = data.setdefault("presets", [])
    data["presets"] = [item for item in presets if item.get("id") != preset["id"]] + [preset]
    _write(data)
    return preset


@router.delete("/api/u4/presets/{preset_id}")
async def delete_preset(preset_id: str, services: Annotated[AppServices, Depends(get_app_services)]) -> dict[str, Any]:
    del services
    data = _read()
    data["presets"] = [item for item in data.get("presets", []) if item.get("id") != preset_id]
    _write(data)
    return {"deleted": True}


def push_event_enabled(settings: dict[str, Any], event: str) -> bool:
    from atlas.notifications.busy import defer, status
    if status()["busy"]:
        defer("Mobile push", event)
        return False
    push = settings.get("mobile_push") or {}
    return bool(push.get("enabled") and (push.get("events") or {}).get(event))


__all__ = ["router", "normalize_chatgpt_conversations", "push_event_enabled", "create_settings_proposal", "_read", "_write"]
