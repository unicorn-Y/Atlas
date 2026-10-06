"""UnifiedMemoryFacade — the single Atlas-side composition point over MemoryOS.

T01.1 边界：
  * 组合 :class:`UnifiedMemoryClient`，配置读取现有 ``AtlasConfig`` 新 namespace
    ``memory.unified``（enabled / service_url / subject_binding / internal_token /
    timeout_seconds），连接地址默认本地 ``http://127.0.0.1:8099``。
  * **不管理第二份事实、不写本地库** —— 所有状态都在 MemoryOS；断连时异常向上抛，
    绝不 fallback 读另一个旧事实库冒充统一（01_contracts.md §8）。
  * 模型无关：不知道任何模型/部署名；subject_binding 来自配置。
"""

from __future__ import annotations

import os
from typing import Any

from atlas.config import AtlasConfig
from atlas.memory.unified_client import (
    CONTRACT_VERSION,
    UnifiedMemoryClient,
    observation_content_hash,
)

DEFAULT_SERVICE_URL = "http://127.0.0.1:8099"
DEFAULT_SUBJECT_BINDING = "subject-default"


class UnifiedMemoryFacade:
    """轻量装配层：recall_for_conversation / observe_batch / status。"""

    def __init__(self, config: AtlasConfig | None = None,
                 client: UnifiedMemoryClient | None = None) -> None:
        self._config = config if config is not None else AtlasConfig()
        if client is not None:
            self._client: UnifiedMemoryClient | None = client
        else:
            self._client = None

    # ------------------------------------------------------------------ 配置

    @property
    def enabled(self) -> bool:
        return bool(self._config.get("memory.unified.enabled", False))

    @property
    def service_url(self) -> str:
        return str(self._config.get("memory.unified.service_url") or DEFAULT_SERVICE_URL)

    @property
    def subject_binding(self) -> str:
        """服务接线/配置绑定的记忆主体 —— 不是工具输出或用户上传 JSON 可改的。"""
        return str(self._config.get("memory.unified.subject_binding")
                   or DEFAULT_SUBJECT_BINDING)

    @property
    def internal_token(self) -> str | None:
        token = self._config.get("memory.unified.internal_token")
        if token:
            return str(token)
        return os.environ.get("MEMORYOS_INTERNAL_TOKEN") or None

    @property
    def timeout_seconds(self) -> float:
        try:
            return float(self._config.get("memory.unified.timeout_seconds", 5.0))
        except (TypeError, ValueError):
            return 5.0

    def client(self) -> UnifiedMemoryClient:
        if self._client is None:
            self._client = UnifiedMemoryClient(
                service_url=self.service_url, internal_token=self.internal_token,
                timeout=self.timeout_seconds)
        return self._client

    def default_context(self, **overrides: Any) -> dict[str, Any]:
        """按配置绑定构造 MemoryContext 骨架（§1 九字段；显式字段优先）。"""
        context = {
            "owner_id": overrides.pop("owner_id",
                                      self._config.get("memory.unified.owner_id")
                                      or "owner-local"),
            "memory_subject_id": overrides.pop("memory_subject_id",
                                               self.subject_binding),
            "client_id": overrides.pop("client_id", "atlas-desktop"),
            "actor_id": overrides.pop("actor_id", "atlas-main"),
            "runtime_session_id": overrides.pop("runtime_session_id", ""),
            "task_id": overrides.pop("task_id", None),
            "project_id": overrides.pop("project_id", None),
            "environment_id": overrides.pop("environment_id", "windows"),
            "model_deployment_id": overrides.pop("model_deployment_id", None),
        }
        context.update(overrides)
        return context

    # ------------------------------------------------------------------ 能力

    async def recall_for_conversation(self, query: str,
                                      budget: dict[str, Any] | None = None,
                                      *, context: dict[str, Any] | None = None,
                                      purpose: str = "CONVERSATION") -> dict[str, Any]:
        """装配给模型上下文的轻量结构。

        返回字段按 §5：read_id / authority_revision / context_items（每项必带
        record_ref/revision、epistemic_kind、适用限制与来源）/ source_snippets /
        conflicts / missing_evidence / context_hash / fallback_mode。
        服务不可达 → ServiceUnavailable 向上抛（不吞成空列表）。
        """
        if not self.enabled:
            return {"enabled": False, "reason": "MEMORY_UNIFIED_DISABLED",
                    "context_items": [], "source_snippets": [], "conflicts": [],
                    "missing_evidence": [{"reason": "MEMORY_UNIFIED_DISABLED"}]}
        request: dict[str, Any] = {
            "context": context or self.default_context(),
            "query": query,
            "purpose": purpose,
        }
        if budget:
            request["budget"] = budget
        response = await self.client().recall(request)
        return {
            "enabled": True,
            "read_id": response.get("read_id"),
            "authority_revision": response.get("authority_revision"),
            "context_hash": response.get("context_hash"),
            "fallback_mode": response.get("fallback_mode"),
            "trace_ref": response.get("trace_ref"),
            "context_items": [
                {
                    "record_ref": item.get("record_ref"),
                    "revision": item.get("record_revision"),
                    "facet": item.get("facet"),
                    "lifecycle": item.get("lifecycle"),
                    "epistemic_kind": item.get("epistemic_kind"),
                    "content": item.get("content"),
                    "source_refs": item.get("source_refs"),
                    "applicability": item.get("applicability"),
                    "valid_time": item.get("valid_time"),
                }
                for item in response.get("context_items", [])
            ],
            "source_snippets": response.get("source_snippets", []),
            "conflicts": response.get("conflicts", []),
            "missing_evidence": response.get("missing_evidence", []),
        }

    async def observe_batch(self, batch: dict[str, Any]) -> dict[str, Any]:
        """发送 ObservationBatch；为缺失 content_hash 的观察按契约 §2 规则补算。

        不改写调用方已有的业务字段；主体绑定仅在没有提供 context 时注入。
        """
        if not self.enabled:
            from atlas.memory.unified_client import ServiceUnavailable

            raise ServiceUnavailable(
                "unified memory disabled (memory.unified.enabled=false); "
                "observe must not silently drop observations")
        payload = {
            "contract_version": batch.get("contract_version", CONTRACT_VERSION),
            "event_class": batch.get("event_class", "PRODUCTION"),
            "context": batch.get("context") or self.default_context(),
            "observations": [],
        }
        for observation in batch.get("observations", []):
            obs = dict(observation)
            if not obs.get("content_hash"):
                obs["content_hash"] = observation_content_hash(obs)
            payload["observations"].append(obs)
        return await self.client().observe(payload)

    async def status(self) -> dict[str, Any]:
        """接线/水位/outbox/模型 worker 状态；disabled 时如实返回禁用状态。"""
        if not self.enabled:
            return {"enabled": False, "reason": "MEMORY_UNIFIED_DISABLED"}
        return await self.client().get_status()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
