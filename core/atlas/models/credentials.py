"""AtlasCredentialPool — 多密钥轮换池（hermes 凭据池协议的 Atlas 精简实现，C5 契约 §3 B2）。

协议来源：hermes-agent@e287231（MIT）。冷却矩阵常量与判定语义对照
agent/credential_pool.py@e287231，hermes 侧调用点逐一核实如下：

- agent/agent_init.py:425  _finalize_routing —— agent 构造期用
  credential_pool_matches_provider(pool, agent.provider, base_url=agent.base_url) 校验，
  不通过即丢弃池 → ``provider`` 属性必须是 hermes provider id（本类从 catalog 解析）。
- agent/agent_init.py:899  ``pool.has_credentials() and not pool.has_available(model=...)``
- agent/agent_runtime_helpers.py:779  _failed_credential_identity —— 遍历 entries() 按
  e.id / e.runtime_api_key 匹配失败凭据，pool.current() 兜底。
- agent/agent_runtime_helpers.py:906  recover_with_credential_pool —— 读 pool.provider、
  mark_exhausted_and_rotate(status_code=, error_context=, api_key_hint=, credential_id=,
  failure_reason=, model=)；401/403 先试 pool.try_refresh_matching(...)，返回 None 即走轮换。
- agent/agent_runtime_helpers.py:1199  pool.next_available_at(model=)（epoch 秒或 None）
- agent/agent_runtime_helpers.py:1243  pool.select(model=) / pool.has_available(model=)
- agent/agent_runtime_helpers.py:1277  pool.reclaim(id, model=)
- run_agent.py:224  pool.has_available() and len(pool.entries()) > 1
- agent/client_lifecycle.py:951  _swap_credential 读 entry 的 runtime_api_key、
  runtime_base_url/base_url（空 → 沿用 agent 当前 base_url）与 id；恢复路径的 per-turn
  revert 判定读 entry.priority（本实现恒 0，该分支不触发）。

与 hermes 的有意差异（静态 API key 池，无 OAuth/DEAD/lease/策略）：
- try_refresh_matching() 恒 None（无刷新能力，hermes 401 路径随即轮换）；
  try_refresh_current() 返回 current()（凭据不变，供 auxiliary client 探活）。
- 身份对不上任何条目时不标记、仅在确有第二个可用 key 时轮换（hermes _rotate_unmatched
  的 streak 计数省略：Atlas 的 hint 均来自本池条目）。
- 模型级 429（C5 契约 §3 B2）：mark_exhausted_and_rotate 带 model 且状态为 429（非 billing
  语义）或 failure_reason="model_entitlement" 时，只写 model_cooldowns[model]，凭据对其余
  模型仍可用。hermes 上游（agent/credential_pool_model_cooldowns.py::_is_model_scoped_failure）
  仅对 provider=="anthropic" 启用该路径；Atlas 对 16 家 catalog 一律生效。
- sole-credential 60s 短冷却在标记时点判定（hermes 每次读取时重算）。

冷却矩阵（秒数常量抄自 agent/credential_pool.py@e287231）：
- 401/403 → 5min（差异：hermes 仅 401 短冷却、403 走 1h 默认；C5 契约 §3 B2 规定 401/403 同判）；
- 429 → 1h；其余状态 → 1h；billing（402 或 failure_reason="billing"）→ 1h；
- 唯一 key 且非 billing → 60s；failure_reason="billing_unverified" → 60s；
- error_context 的 reset_at/resets_at/retry_until（epoch 秒/毫秒/ISO-8601）优先；
  retry_after/resets_in_seconds 按相对秒数；message 内 "retry after N s" / "resets in …"
  文法兜底（hermes agent/retry_utils.py 同名文法的精简版）。

存储：密钥元数据（含池状态）在 settings 的 providers.<pid>.keys[i]；密钥原文在系统凭据库
（KeyringCredentialStore，service="Atlas"，account=atlas.provider.<pid>.key.<key_id>）。
settings 写入为 load+update 合并写（按 key id 合并，不覆盖其他键/其他服务商行）；
密钥原文永不写入 settings/日志。
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

import structlog

from atlas.config import load_user_settings, save_user_settings

log = structlog.get_logger()

# --- 冷却矩阵常量（来源：hermes-agent@e287231 agent/credential_pool.py） ----------------

STATUS_OK = "ok"
STATUS_EXHAUSTED = "exhausted"

EXHAUSTED_TTL_401_SECONDS = 5 * 60  # hermes EXHAUSTED_TTL_401_SECONDS（C5：403 同判）
EXHAUSTED_TTL_429_SECONDS = 60 * 60  # hermes EXHAUSTED_TTL_429_SECONDS
EXHAUSTED_TTL_DEFAULT_SECONDS = 60 * 60  # hermes EXHAUSTED_TTL_DEFAULT_SECONDS
EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS = 60  # hermes EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS

FAILURE_REASON_BILLING = "billing"  # hermes FAILURE_REASON_BILLING（字符串，避免 import 分类器）
FAILURE_REASON_BILLING_UNVERIFIED = "billing_unverified"  # hermes #82154
FAILURE_REASON_MODEL_ENTITLEMENT = "model_entitlement"  # hermes #71970

_MAX_ERROR_SUMMARY = 200  # last_error 摘要截断长度（上游错误文本，不含密钥）

# --- 上游 reset 时间解析 ---------------------------------------------------------------

# 绝对时刻键（epoch 秒/毫秒/ISO-8601），语义同 hermes _normalize_error_context。
_ABSOLUTE_RESET_KEYS = ("reset_at", "resets_at", "retry_until")
# 相对秒数键（Atlas 扩展：B3 组装 error_context 可直接透传 retry-after 头/体字段）。
_RELATIVE_RESET_KEYS = ("retry_after", "resets_in_seconds")

# 自由文本 reset 文法（精简自 hermes agent/retry_utils.py RETRY_DELAY_PATTERNS，顺序保持
# "retry after N s" 优先于 "resets in …"）。
_RETRY_AFTER_RE = re.compile(
    r"retry\s+(?:after\s+)?(\d+(?:\.\d+)?)\s*(?:sec|secs|seconds|s\b)", re.IGNORECASE,
)
_RESETS_IN_RE = re.compile(
    r"resets?\s+in\s+"
    r"(?:(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)\b\s*)?"
    r"(?:(\d+(?:\.\d+)?)\s*(?:s|sec|secs|second|seconds)\b)?",
    re.IGNORECASE,
)


def _parse_absolute_timestamp(value: Any) -> float | None:
    """epoch 秒 / epoch 毫秒 / ISO-8601 → epoch 秒；无法解析返回 None（照抄 hermes 语义）。"""
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        if numeric <= 0:
            return None
        return numeric / 1000.0 if numeric > 1_000_000_000_000 else numeric
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            numeric = float(raw)
            return numeric / 1000.0 if numeric > 1_000_000_000_000 else numeric
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _resets_in_seconds(match: re.Match) -> float | None:
    """``resets in 4hr 5min`` / ``resets in 30s`` → 秒；无单位数字不算命中。"""
    if not any(match.groups()):
        return None
    hours, minutes, seconds = match.groups()
    return float(hours or 0) * 3600 + float(minutes or 0) * 60 + float(seconds or 0)


def _message_retry_delay(message: str) -> float | None:
    """从上游错误文本解析“多少秒后恢复”，解析不出返回 None。"""
    if not message:
        return None
    retry_after = _RETRY_AFTER_RE.search(message)
    if retry_after:
        return float(retry_after.group(1))
    resets_in = _RESETS_IN_RE.search(message)
    if resets_in:
        return _resets_in_seconds(resets_in)
    return None


def _normalize_error_context(error_context: Any, *, now: float) -> dict[str, Any]:
    """提取 reason/message 与上游 reset 时刻（epoch 秒），语义对齐 hermes 同名函数。"""
    if not isinstance(error_context, dict):
        return {}
    normalized: dict[str, Any] = {}
    for key in ("reason", "message"):
        value = error_context.get(key)
        if isinstance(value, str) and value.strip():
            normalized[key] = value.strip()
    reset_at: float | None = None
    for key in _ABSOLUTE_RESET_KEYS:
        parsed = _parse_absolute_timestamp(error_context.get(key))
        if parsed is not None:
            reset_at = parsed
            break
    if reset_at is None:
        for key in _RELATIVE_RESET_KEYS:
            raw = error_context.get(key)
            if raw is None or isinstance(raw, bool):
                continue
            try:
                reset_at = now + max(0.0, float(raw))
                break
            except (TypeError, ValueError):
                continue
    if reset_at is None:
        delay = _message_retry_delay(normalized.get("message") or "")
        if delay is not None:
            reset_at = now + delay
    if reset_at is not None:
        normalized["reset_at"] = float(reset_at)
    return normalized


def _exhausted_ttl(
    status_code: int | None,
    *,
    sole_credential: bool = False,
    failure_reason: str | None = None,
) -> int:
    """按致败 HTTP 状态定冷却秒数（对照 hermes _exhausted_ttl@e287231，差异见模块头注）。"""
    is_billing = status_code == 402 or failure_reason == FAILURE_REASON_BILLING
    if status_code in (401, 403) and not is_billing:
        return EXHAUSTED_TTL_401_SECONDS
    base = EXHAUSTED_TTL_429_SECONDS if status_code == 429 else EXHAUSTED_TTL_DEFAULT_SECONDS
    if failure_reason == FAILURE_REASON_BILLING_UNVERIFIED and status_code != 402:
        return min(base, EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS)
    if sole_credential and not is_billing:
        return min(base, EXHAUSTED_TTL_SOLE_CREDENTIAL_SECONDS)
    return base


def _error_summary(status_code: int | None, normalized: dict[str, Any]) -> str:
    """last_error 摘要（仅上游状态/错误文本，不含密钥）。"""
    parts = []
    if status_code is not None:
        parts.append(f"HTTP {status_code}")
    for key in ("reason", "message"):
        if normalized.get(key):
            parts.append(str(normalized[key]))
    text = " — ".join(parts) if parts else "unknown upstream error"
    return text[:_MAX_ERROR_SUMMARY]


def model_cooldown_until(
    entry: AtlasCredentialEntry, model: str | None, now: float,
) -> float | None:
    """阻塞 *entry* 用于 *model* 的模型级冷却时刻；无 → None（照抄 hermes 同名函数语义：
    不知道 model 的调用方从保守处理——任何活跃模型冷却都算阻塞）。"""
    cooldowns = entry.model_cooldowns
    values = cooldowns.values() if not model else (cooldowns.get(model),)
    active = [float(until) for until in values if isinstance(until, (int, float)) and until > now]
    return max(active) if active else None


class AtlasCredentialEntry:
    """单条密钥的运行时视图；字段语义对齐 hermes PooledCredential 的运行时子集。

    状态存在 settings 的 key 元数据 dict（``_meta``）里，属性直读、变更经池落盘；
    密钥原文经 ``runtime_api_key`` 懒读系统凭据库并缓存（读失败返回空串不缓存）。
    """

    # hermes 恢复路径的 revert 判定读 entry.priority；Atlas 无优先级（fill-first 按
    # settings 顺序），恒 0 使该分支不触发。
    priority: int = 0

    def __init__(self, meta: dict[str, Any], pool: AtlasCredentialPool) -> None:
        self._meta = meta
        self._pool = pool
        self._runtime_key_cache: str | None = None

    @property
    def id(self) -> str:
        return str(self._meta.get("id") or "")

    @property
    def label(self) -> str:
        return str(self._meta.get("label") or "")

    @property
    def base_url(self) -> str | None:
        """Atlas 不做 per-key 端点（base_url 属于 provider/模型配置），实际恒 None；
        hermes _swap_credential 对空值沿用 agent 当前 base_url。"""
        base = self._meta.get("base_url")
        return str(base) if base else None

    @property
    def runtime_base_url(self) -> str | None:
        # hermes _swap_credential / credential_pool_entry_serves_endpoint 读它。
        return self.base_url

    @property
    def runtime_api_key(self) -> str:
        """密钥原文（懒读系统凭据库；读不到为空串 → 调用方按不可用跳过）。"""
        if self._runtime_key_cache is not None:
            return self._runtime_key_cache
        try:
            secret = self._pool._store.get(self._pool._keyring_account(self.id))
        except Exception as exc:
            log.debug("credentials.keyring_read_failed", key_id=self.id, error=str(exc), exc_info=True)
            return ""
        if secret:
            self._runtime_key_cache = str(secret)
        return str(secret or "")

    @property
    def last_status(self) -> str | None:
        value = self._meta.get("last_status")
        return str(value) if value else None

    @property
    def last_error(self) -> str | None:
        value = self._meta.get("last_error")
        return str(value) if value else None

    @property
    def cooldown_until(self) -> float | None:
        value = self._meta.get("cooldown_until")
        return float(value) if isinstance(value, (int, float)) else None

    @property
    def model_cooldowns(self) -> dict[str, float]:
        return dict(self._meta.get("model_cooldowns") or {})

    @property
    def request_count(self) -> int:
        return int(self._meta.get("request_count") or 0)

    # --- 以下由 AtlasCredentialPool 内部调用（状态变更统一落盘） ---

    def _mark_exhausted(self, *, last_error: str, cooldown_until: float) -> None:
        self._meta["last_status"] = STATUS_EXHAUSTED
        self._meta["last_error"] = last_error
        self._meta["cooldown_until"] = float(cooldown_until)

    def _clear_status(self) -> None:
        self._meta["last_status"] = STATUS_OK
        self._meta["last_error"] = None
        self._meta["cooldown_until"] = None

    def _set_model_cooldown(self, model: str, until: float) -> None:
        merged = dict(self._meta.get("model_cooldowns") or {})
        merged[model] = max(float(until), float(merged.get(model, 0.0)))
        self._meta["model_cooldowns"] = merged

    def _bump_request_count(self) -> None:
        self._meta["request_count"] = int(self._meta.get("request_count") or 0) + 1


def _clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
    """落盘前去掉空状态字段（None / 空表），保留 id/label/added_at 等用户元数据。"""
    return {key: value for key, value in meta.items() if value is not None and value != {}}


class AtlasCredentialPool:
    """同服务商多密钥轮换池：has_credentials/has_available/select/reclaim/mark_exhausted_and_rotate
    等方法与 hermes agent 的 ``_credential_pool`` 协议子集兼容（调用点见模块头注）。"""

    def __init__(
        self,
        provider_id: str,
        *,
        store: Any | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        self._provider_id = str(provider_id or "").strip()
        # credential_pool_matches_provider 用 agent.provider（hermes provider id）比较；
        # catalog id（settings 键）与 hermes id 不同（如 qwen→alibaba）时在这里归一。
        from atlas.models.catalog import get_provider

        catalog_entry = get_provider(self._provider_id)
        self.provider = str((catalog_entry or {}).get("hermes_provider") or self._provider_id)
        if store is not None:
            self._store = store
        else:
            from atlas.telegram import KeyringCredentialStore

            self._store = KeyringCredentialStore()
        self._now: Callable[[], float] = now if now is not None else time.time
        self._metas: list[dict[str, Any]] = self._load_key_metas()
        self._entries = [AtlasCredentialEntry(meta, self) for meta in self._metas]
        self._current_id: str | None = None

    # --- 存取 ------------------------------------------------------------

    def _keyring_account(self, key_id: str) -> str:
        return f"atlas.provider.{self._provider_id}.key.{key_id}"

    def _load_key_metas(self) -> list[dict[str, Any]]:
        providers = load_user_settings().get("providers")
        entry = providers.get(self._provider_id) if isinstance(providers, dict) else None
        keys = entry.get("keys") if isinstance(entry, dict) else None
        if not isinstance(keys, list):
            return []
        return [dict(row) for row in keys if isinstance(row, dict) and str(row.get("id") or "")]

    def _persist(self) -> None:
        """合并写：load → 按 key id 替换本池行 → save；其他键/其他服务商行原样保留。"""
        data = load_user_settings()
        providers = data.get("providers")
        if not isinstance(providers, dict):
            providers = {}
        provider_entry = providers.get(self._provider_id)
        if not isinstance(provider_entry, dict):
            provider_entry = {}
        rows = provider_entry.get("keys")
        rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
        ours = {str(meta.get("id")): meta for meta in self._metas}
        merged: list[dict[str, Any]] = []
        for row in rows:
            row_id = str(row.get("id") or "")
            merged.append(_clean_meta(ours.pop(row_id)) if row_id in ours else row)
        provider_entry["keys"] = merged
        providers[self._provider_id] = provider_entry
        data["providers"] = providers
        save_user_settings(data)

    # --- 只读协议 ---------------------------------------------------------

    def has_credentials(self) -> bool:
        return bool(self._entries)

    def entries(self) -> list[AtlasCredentialEntry]:
        return list(self._entries)

    def current(self) -> AtlasCredentialEntry | None:
        if not self._current_id:
            return None
        return self._find(lambda e: e.id == self._current_id)

    def _find(
        self, predicate: Callable[[AtlasCredentialEntry], bool],
    ) -> AtlasCredentialEntry | None:
        return next((entry for entry in self._entries if predicate(entry)), None)

    def _is_sole_credential(self) -> bool:
        return len(self._entries) <= 1

    def _available(
        self, *, clear_expired: bool = False, model: str | None = None,
    ) -> list[AtlasCredentialEntry]:
        """不在冷却中的条目（fill-first 顺序 = settings 列表顺序）。

        keyring 读不到原文的条目视为不可用（hermes 对空 token 同样跳过）；
        clear_expired 时把到期的 exhausted 状态清回 ok 并落盘（hermes 同语义）。
        """
        now = float(self._now())
        available: list[AtlasCredentialEntry] = []
        cleared = False
        for entry in self._entries:
            if not entry.runtime_api_key:
                continue
            if model_cooldown_until(entry, model, now) is not None:
                continue
            if entry.last_status == STATUS_EXHAUSTED:
                until = entry.cooldown_until
                if until is not None and now < until:
                    continue
                if clear_expired:
                    entry._clear_status()
                    cleared = True
            available.append(entry)
        if cleared:
            self._persist()
        return available

    def has_available(self, *, model: str | None = None) -> bool:
        return bool(self._available(model=model))

    def next_available_at(self, *, model: str | None = None) -> float | None:
        """最早的条目恢复时刻（epoch 秒）；现在就有可用 / 无可恢复信息时返回 None。"""
        if self._available(model=model):
            return None
        now = float(self._now())
        candidates: list[float] = []
        for entry in self._entries:
            if entry.last_status == STATUS_EXHAUSTED and entry.cooldown_until is not None:
                candidates.append(float(entry.cooldown_until))
            until = model_cooldown_until(entry, model, now)
            if until is not None:
                candidates.append(float(until))
        return min(candidates) if candidates else None

    def peek(self) -> AtlasCredentialEntry | None:
        current = self.current()
        if current is not None:
            return current
        return next(iter(self._available()), None)

    # --- 选择 ------------------------------------------------------------

    def select(self, *, model: str | None = None) -> AtlasCredentialEntry | None:
        """选第一个可用条目（fill-first），递增 request_count 并落盘。"""
        available = self._available(clear_expired=True, model=model)
        if not available:
            self._current_id = None
            return None
        entry = available[0]
        entry._bump_request_count()
        self._persist()
        self._current_id = entry.id
        return entry

    def reclaim(
        self, credential_id: str, *, model: str | None = None,
    ) -> AtlasCredentialEntry | None:
        """条目 *credential_id* 冷却到期后的归还查询；不计请求、不改游标（hermes 同语义）。"""
        available = self._available(clear_expired=True, model=model)
        return next((entry for entry in available if entry.id == str(credential_id)), None)

    def entry_id_for_api_key(self, api_key_hint: str | None = None) -> str | None:
        """当前在用密钥的稳定 id（hermes sync_credential_pool_entry_id 调用）。"""
        current = self.current()
        if current is not None and (
            api_key_hint is None or current.runtime_api_key == api_key_hint
        ):
            return current.id
        if api_key_hint is None:
            return None
        matches = [entry for entry in self._entries if entry.runtime_api_key == api_key_hint]
        return matches[0].id if len(matches) == 1 else None

    # --- 静态 API key 池没有刷新能力（协议占位，见模块头注） ---------------

    def try_refresh_matching(
        self, api_key_hint: str | None = None, credential_id: str | None = None,
    ) -> AtlasCredentialEntry | None:
        """恒 None：hermes 401/403 路径收到 None 即转入 mark_exhausted_and_rotate 轮换。"""
        return None

    def try_refresh_current(self) -> AtlasCredentialEntry | None:
        """无刷新动作，返回当前条目（auxiliary client 探活路径）。"""
        return self.current()

    # --- 轮换 ------------------------------------------------------------

    def _find_by_key(self, api_key_hint: str) -> AtlasCredentialEntry | None:
        return next(
            (entry for entry in self._entries if entry.runtime_api_key == api_key_hint), None,
        )

    def _identify_failed_entry(
        self, credential_id: str | None, api_key_hint: str | None,
    ) -> AtlasCredentialEntry | None:
        """按 id / 密钥原文定位失败条目；id 与 key 冲突时信任 key（hermes #79156）。"""
        entry: AtlasCredentialEntry | None = None
        if credential_id:
            entry = self._find(lambda e: e.id == str(credential_id))
            if entry is not None and api_key_hint and entry.runtime_api_key != api_key_hint:
                entry = self._find_by_key(api_key_hint)
        if entry is None and api_key_hint:
            entry = self._find_by_key(api_key_hint)
        return entry

    @staticmethod
    def _is_model_scoped_failure(
        status_code: int | None, model: str | None, failure_reason: str | None,
    ) -> bool:
        """模型级失败：只冷却 (key, model)，凭据对其余模型仍可用。

        判定条件同 hermes（429 + 非 billing 语义 + model_entitlement），但不限
        provider=="anthropic"（C5 契约 §3 B2，见模块头注“有意差异”）。
        """
        if not model:
            return False
        if failure_reason == FAILURE_REASON_MODEL_ENTITLEMENT:
            return True
        return (
            status_code == 429
            and failure_reason not in (FAILURE_REASON_BILLING, FAILURE_REASON_BILLING_UNVERIFIED)
        )

    def mark_exhausted_and_rotate(
        self,
        *,
        status_code: int | None = None,
        error_context: dict[str, Any] | None = None,
        api_key_hint: str | None = None,
        credential_id: str | None = None,
        failure_reason: str | None = None,
        model: str | None = None,
    ) -> AtlasCredentialEntry | None:
        """标记失败条目进入冷却并轮换；返回下一个可用条目，无处可换时 None。

        冷却矩阵见模块头注；状态（last_status/last_error/cooldown_until/model_cooldowns/
        request_count）持久化到 settings 的 providers.<pid>.keys[i]。
        """
        identity_supplied = bool(credential_id or api_key_hint)
        entry = self._identify_failed_entry(credential_id, api_key_hint)
        if entry is None and identity_supplied:
            # 身份对不上：不标记任何条目（hermes _rotate_unmatched），仅在确有第二个
            # 可用 key 时轮换——单条目池返回 None 让失败向上浮出。
            self._current_id = None
            if len(self._available(clear_expired=True)) <= 1:
                return None
            return self.select()
        if entry is None:
            entry = self.current() or next(iter(self._available(clear_expired=True)), None)
        if entry is None:
            return None
        normalized = _normalize_error_context(error_context, now=float(self._now()))
        if self._is_model_scoped_failure(status_code, model, failure_reason):
            until = normalized.get("reset_at") or float(self._now()) + _exhausted_ttl(
                429, sole_credential=self._is_sole_credential(),
            )
            entry._set_model_cooldown(str(model), float(until))
            log.info(
                "credentials.model_cooldown",
                provider=self.provider, key_id=entry.id, model=model,
            )
            self._persist()
            self._current_id = None
            return self.select(model=model)
        until = normalized.get("reset_at") or float(self._now()) + _exhausted_ttl(
            status_code, sole_credential=self._is_sole_credential(), failure_reason=failure_reason,
        )
        entry._mark_exhausted(
            last_error=_error_summary(status_code, normalized), cooldown_until=float(until),
        )
        log.info(
            "credentials.exhausted",
            provider=self.provider, key_id=entry.id, status_code=status_code,
        )
        self._persist()
        self._current_id = None
        next_entry = self.select()
        if next_entry is not None and next_entry.id == entry.id:
            # hermes #97315：轮换又发回刚标记的条目 = 没有真正的恢复，按失败处理。
            self._current_id = None
            return None
        if next_entry is not None:
            log.info("credentials.rotated", provider=self.provider, to_key_id=next_entry.id)
        return next_entry
