"""M5 缓存未命中原因诊断（C5 契约 §3）。

每次 run 结束记录 system/tools/history 三层签名（进程内，每会话保留最近 8 次）；
命中率明显下降时与上一次可比请求逐层比对，给出本地可证明的原因。
"""

from __future__ import annotations

import hashlib
from collections import deque
from typing import Any

_MAX_SAMPLES = 8
# 进程内状态：会话 id → 最近请求的 {"system","tools","history","hit_rate"}。
_layers: dict[str, deque[dict[str, Any]]] = {}

TOOLS_CHANGED = "工具定义变了（可能是 MCP 服务器重连）"
SYSTEM_CHANGED = "系统提示词变了"
HISTORY_CHANGED = "历史前缀变了（新消息/压缩/分支）"
UNKNOWN_REASON = "缓存未命中原因未知（可能超过缓存有效期）"


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def record_layer_hashes(
    conversation_id: str, system_prompt: str, tools_signature: str, history_signature: str,
) -> dict[str, str]:
    """记录一次请求的三层签名，返回 {"system","tools","history"} 的 sha16。"""
    hashes = {
        "system": _sha16(system_prompt or ""),
        "tools": _sha16(tools_signature or ""),
        "history": _sha16(history_signature or ""),
    }
    layers = _layers.setdefault(str(conversation_id or ""), deque(maxlen=_MAX_SAMPLES))
    layers.append({**hashes, "hit_rate": None})
    return hashes


def explain_cache_drop(
    conversation_id: str, current: dict[str, str],
    cached_input_tokens: int, input_tokens: int,
) -> str | None:
    """与上一次可比请求比对：命中明显下降才给原因，否则 None。

    current 是本次 record_layer_hashes 的返回值；上次命中率来自本会话
    上一次 explain_cache_drop 的计算结果（run_usage 每轮都会调用）。
    """
    key = str(conversation_id or "")
    if input_tokens <= 0:
        return None
    rate_now = max(0, cached_input_tokens) / input_tokens
    layers = _layers.get(key)
    if not layers:
        return None
    # 上一次命中率挂在上一条记录上（本次记录刚由 record_layer_hashes 追加）。
    rate_before = layers[-2].get("hit_rate") if len(layers) >= 2 else None
    layers[-1]["hit_rate"] = rate_now
    if rate_before is None or not (
        (rate_now <= 0.05 < rate_before) or (rate_before - rate_now > 0.5)
    ):
        return None
    previous = layers[-2]
    if str(current.get("tools")) != str(previous.get("tools")):
        return TOOLS_CHANGED
    if str(current.get("system")) != str(previous.get("system")):
        return SYSTEM_CHANGED
    if str(current.get("history")) != str(previous.get("history")):
        return HISTORY_CHANGED
    return UNKNOWN_REASON
