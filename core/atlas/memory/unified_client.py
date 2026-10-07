"""UnifiedMemoryClient — typed HTTP transport to the MemoryOS unified API.

契约来源：docs/plan/UNIFIED-MEMORY/01_contracts.md（§5 客户端签名、§6 路由表）。

边界（T01.1）：
  * 客户端**不执行 SQL**、不直接 import MemoryOS Python 包 —— 唯一通道是 HTTP。
  * 每个方法都有真实 HTTP 实现；服务端 501 FEATURE_NOT_READY → :class:`FeatureNotReady`
    （保留 route），连接失败/超时 → :class:`ServiceUnavailable`（不吞成空列表/None），
    409 → :class:`RevisionConflict`（保留 code/detail），423 → :class:`ErasureBlocked`，
    403 → :class:`ForbiddenSubject`，422 → :class:`ContractViolation`。
  * 模型无关：本模块不知道任何模型/部署名。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

#: 与 MemoryOS service/unified/contracts.py 相同的契约版本
CONTRACT_VERSION = "UM-WIN-1.0"

#: §2 内容哈希覆盖的业务字段（与 MemoryOS 侧 HASH_BASIS_FIELDS 一致；
#: 运输重试时间不进哈希）
HASH_BASIS_FIELDS = (
    "source_event_id",
    "source_kind",
    "source_object_id",
    "source_revision",
    "event_action",
    "occurred_at",
    "source_timezone",
    "time_status",
    "speaker_role",
    "epistemic_kind",
    "content",
    "locator",
    "media_refs",
    "derived_from",
)


def canonical_json(obj: Any) -> str:
    """稳定序列化（与 MemoryOS db.canonical_json 同规则：排序 key、紧凑分隔符）。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def observation_content_hash(observation: dict[str, Any]) -> str:
    """按契约 §2 计算观察内容哈希（服务端会重算校验，不一致 → 422）。"""
    basis = {key: observation.get(key) for key in HASH_BASIS_FIELDS}
    digest = hashlib.sha256(canonical_json(basis).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ------------------------------------------------------------------ 错误类型

class UnifiedMemoryError(Exception):
    """统一记忆客户端错误基类：保留 status/code/detail，绝不静默吞掉。"""

    def __init__(self, message: str, *, status_code: int | None = None,
                 code: str | None = None, detail: Any = None,
                 route: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.route = route


class ServiceUnavailable(UnifiedMemoryError):
    """服务不可达 / 超时 / 5xx。调用方应保留观察、显示 DEGRADED，不得 fallback 旧库。"""


class FeatureNotReady(UnifiedMemoryError):
    """服务端该路由对应业务尚未实现（501 FEATURE_NOT_READY），保留 route。"""


class RevisionConflict(UnifiedMemoryError):
    """同 ID 异内容 / 版本冲突（409），保留服务端 code 与 detail。"""


class ErasureBlocked(UnifiedMemoryError):
    """被 erasure 屏障阻断（423）：删除后不可复活。"""


class ForbiddenSubject(UnifiedMemoryError):
    """主体绑定校验失败（403 FOREIGN_SUBJECT）。"""


class ContractViolation(UnifiedMemoryError):
    """请求违反传输契约（422）。"""


class UnauthorizedError(UnifiedMemoryError):
    """内部凭据缺失或不匹配（401/503）。"""


# ------------------------------------------------------------------ 客户端

class UnifiedMemoryClient:
    """MemoryOS /v1/unified/* 的类型化异步客户端（§5 签名、§6 路由表）。

    ``transport`` 仅用于测试注入（httpx.MockTransport）；生产路径使用真实连接，
    惰性创建（首次调用时建立），不持有任何本地状态/缓存事实。
    """

    def __init__(self, service_url: str, internal_token: str | None = None,
                 timeout: float = 5.0, *, transport: httpx.AsyncBaseTransport | None = None,
                 contract_version: str = CONTRACT_VERSION,
                 frozen_features: frozenset[str] | None = None) -> None:
        self._service_url = service_url.rstrip("/")
        self._internal_token = internal_token
        self._timeout = timeout
        self._transport = transport
        self._contract_version = contract_version
        self._frozen_features = frozen_features
        self._client: httpx.AsyncClient | None = None

    # -- 生命周期 --

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            headers = {"Accept": "application/json"}
            if self._frozen_features is not None:
                from atlas.memory.v1_features import FROZEN_FEATURES_HEADER

                headers[FROZEN_FEATURES_HEADER] = json.dumps(sorted(self._frozen_features))
            if self._internal_token:
                headers["Authorization"] = f"Bearer {self._internal_token}"
            hostname = urlsplit(self._service_url).hostname
            trust_env = hostname not in {"127.0.0.1", "localhost", "::1"}
            self._client = httpx.AsyncClient(
                base_url=self._service_url, timeout=self._timeout,
                headers=headers, transport=self._transport, follow_redirects=False,
                trust_env=trust_env)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> "UnifiedMemoryClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    # -- 传输核心 --

    async def _request(self, method: str, path: str, *, json_body: Any = None,
                       params: dict[str, Any] | None = None) -> Any:
        try:
            response = await self._http().request(
                method, path, json=json_body, params=params)
        except httpx.TimeoutException as exc:
            raise ServiceUnavailable(
                f"unified memory service timeout ({method} {path}): {exc}",
                route=path) from exc
        except httpx.TransportError as exc:
            raise ServiceUnavailable(
                f"unified memory service unreachable ({method} {path}): {exc}",
                route=path) from exc
        return self._decode(method, path, response)

    @staticmethod
    def _safe_json(response: httpx.Response) -> Any:
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    def _decode(self, method: str, path: str, response: httpx.Response) -> Any:
        body = self._safe_json(response)
        if 200 <= response.status_code < 300:
            return body if body is not None else {}

        error = body if isinstance(body, dict) else {}
        code = str(error.get("error") or "")
        message = str(error.get("message") or response.text[:300])
        detail = error.get("details", error)
        common = {"status_code": response.status_code, "code": code or None,
                  "detail": detail, "route": path}
        if response.status_code == 501 and code == "FEATURE_NOT_READY":
            raise FeatureNotReady(
                f"route not implemented upstream: {error.get('route') or path}",
                **common)
        if response.status_code == 409:
            raise RevisionConflict(
                f"conflict on {method} {path}: {code or 'IDEMPOTENCY_CONFLICT'}", **common)
        if response.status_code == 423:
            raise ErasureBlocked(f"erasure barrier blocked {method} {path}", **common)
        if response.status_code == 403:
            raise ForbiddenSubject(
                f"subject rejected on {method} {path}: {code or 'FORBIDDEN'}", **common)
        if response.status_code == 422:
            raise ContractViolation(
                f"contract violation on {method} {path}: "
                f"{message or code or 'validation error'}", **common)
        if response.status_code == 401:
            raise UnauthorizedError(
                f"unified memory auth failed on {method} {path}: {code}", **common)
        if response.status_code == 503:
            # 服务端未就绪 / 内部鉴权未配置 —— 都是"服务当前不可用"
            raise ServiceUnavailable(
                f"unified memory service unavailable (503) on {method} {path}: "
                f"{code or message}", **common)
        if response.status_code >= 500:
            raise ServiceUnavailable(
                f"unified memory service error {response.status_code} on "
                f"{method} {path}: {message}", **common)
        raise UnifiedMemoryError(
            f"unexpected response {response.status_code} on {method} {path}: {message}",
            **common)

    # ------------------------------------------------------------------
    # §5 客户端签名（每个方法都有真实 HTTP 实现；501/错误映射见 _decode）
    # ------------------------------------------------------------------

    async def observe(self, batch: dict) -> dict:
        """POST /v1/unified/observe → ack（receipts、watermarks）。同 ID 异内容 409。"""
        payload = dict(batch)
        payload.setdefault("contract_version", self._contract_version)
        return await self._request("POST", "/v1/unified/observe", json_body=payload)

    async def recall(self, request: dict) -> dict:
        """POST /v1/unified/recall → RecallResponse（read_id/context_items/...）。"""
        return await self._request("POST", "/v1/unified/recall", json_body=request)

    async def evidence(self, record_ref: str, revision: int | None = None) -> dict:
        """GET /v1/unified/evidence/{record_ref} → 原始定位与片段；屏障 410→423 语义。"""
        params: dict[str, Any] = {}
        if revision is not None:
            params["revision"] = revision
        return await self._request(
            "GET", f"/v1/unified/evidence/{record_ref}", params=params or None)

    async def correct(self, request: dict) -> dict:
        """POST /v1/unified/corrections → 修订结果（idempotent；不一致 409）。"""
        return await self._request("POST", "/v1/unified/corrections", json_body=request)

    async def source_changed(self, request: dict) -> dict:
        """POST /v1/unified/sources/change → ack（edit/delete 重试幂等）。"""
        return await self._request("POST", "/v1/unified/sources/change", json_body=request)

    async def update_focus(self, request: dict) -> dict:
        """POST /v1/unified/focus → focus ref（旧运行版本拒绝覆盖）。"""
        return await self._request("POST", "/v1/unified/focus", json_body=request)

    async def attend_focus(self, task_id: str, *, purpose: str = "CONTINUE_TASK",
                           subject: str | None = None,
                           max_records: int | None = None) -> dict:
        """GET /v1/unified/focus/{task_id} → attend 焦点装配（T06.1 / UM06）。

        purpose=CONTINUE_TASK（含近期注意事件）/ PLAN（只装配已提交状态）；
        空 focus → 200 且 found=False（服务端不编造前情）；valid_until 过期 →
        expired=True 且装配节退出。
        """
        params: dict[str, Any] = {"purpose": purpose}
        if subject:
            params["memory_subject_id"] = subject
        if max_records is not None:
            params["max_records"] = int(max_records)
        return await self._request(
            "GET", f"/v1/unified/focus/{task_id}", params=params)

    async def observe_focus(self, focus_id: str, request: dict) -> dict:
        """POST /v1/unified/focus/{focus_id}/observe → 注意事件入工作集
        （T06.1：不改权威快照；404 焦点不存在 / 410 已过期同码映射）。"""
        return await self._request(
            "POST", f"/v1/unified/focus/{focus_id}/observe", json_body=request)

    async def create_intent(self, request: dict) -> dict:
        """POST /v1/unified/intents → intent ref（无直接授权来源只可 PROPOSED）。"""
        return await self._request("POST", "/v1/unified/intents", json_body=request)

    async def transition_intent(self, intent_id: str, request: dict) -> dict:
        """POST /v1/unified/intents/{id}/transition → 新状态（UNKNOWN 先对账）。"""
        return await self._request(
            "POST", f"/v1/unified/intents/{intent_id}/transition", json_body=request)

    async def record_outcome(self, request: dict) -> dict:
        """POST /v1/unified/outcomes → outcome ref（未验证自报不能 SUCCEEDED）。"""
        return await self._request("POST", "/v1/unified/outcomes", json_body=request)

    async def apply_feedback(self, request: dict) -> dict:
        """POST /v1/unified/feedback → ack（反馈不直接把经验 ACTIVE）。"""
        return await self._request("POST", "/v1/unified/feedback", json_body=request)

    async def record_application(self, request: dict) -> dict:
        """POST /v1/unified/applications → application ref（read_id 不可伪造）。"""
        return await self._request("POST", "/v1/unified/applications", json_body=request)

    async def check_dependencies(self, request: dict) -> dict:
        """POST /v1/unified/dependencies/check → VALID/STALE 及差异（动作前检查）。"""
        return await self._request(
            "POST", "/v1/unified/dependencies/check", json_body=request)

    async def get_status(self) -> dict:
        """GET /v1/unified/status → 接线、水位、outbox、模型/worker 状态。"""
        return await self._request("GET", "/v1/unified/status")

    # ------------------------------------------------------------------
    # T01.3 通用代理调用（Atlas /api/unified-memory/* 的唯一传输）
    # ------------------------------------------------------------------

    async def call(self, method: str, path: str, *, json: Any = None,
                   params: dict[str, Any] | None = None) -> Any:
        """透传任意 ``/v1/unified/*`` 契约路由；错误类映射与类型化方法一致。

        只允许 ``/v1/unified/`` 前缀（代理不能变成任意路径转发）；成功返回
        解码后的 JSON body，失败按 _decode 抛对应错误类（501→FeatureNotReady、
        409→RevisionConflict、423→ErasureBlocked、403→ForbiddenSubject、
        422→ContractViolation、超时/断连→ServiceUnavailable）。
        """
        if not path.startswith("/v1/unified/"):
            raise UnifiedMemoryError(
                f"refusing non-unified proxy path: {path!r} "
                "(the unified-memory transport only forwards /v1/unified/* routes)")
        return await self._request(method.upper(), path, json_body=json, params=params)

    # ------------------------------------------------------------------
    # T05.1 受控媒体传输（原始字节上传 / 文件流透传；JSON 走 call）
    # ------------------------------------------------------------------

    async def call_raw(self, method: str, path: str, *, content: bytes | None = None,
                       content_type: str | None = None,
                       params: dict[str, Any] | None = None) -> tuple[int, Any]:
        """原始字节透传（POST /v1/unified/media 上传等）：body/content-type 原样转发。

        返回 (upstream status, decoded JSON)；失败错误类映射与 :meth:`call`
        完全一致。同样只允许 ``/v1/unified/`` 前缀。
        """
        if not path.startswith("/v1/unified/"):
            raise UnifiedMemoryError(
                f"refusing non-unified proxy path: {path!r} "
                "(the unified-memory transport only forwards /v1/unified/* routes)")
        headers = {"Content-Type": content_type} if content_type else None
        try:
            response = await self._http().request(
                method.upper(), path, content=content, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ServiceUnavailable(
                f"unified memory service timeout ({method} {path}): {exc}",
                route=path) from exc
        except httpx.TransportError as exc:
            raise ServiceUnavailable(
                f"unified memory service unreachable ({method} {path}): {exc}",
                route=path) from exc
        return response.status_code, self._decode(method, path, response)

    async def fetch_media_content(self, asset_id: str,
                                  params: dict[str, Any] | None = None) -> httpx.Response:
        """GET /v1/unified/media/{asset_id}/content 的**原始响应**（代理流式转发）。

        不消费 body、不落盘副本 —— 调用方（unified_memory_router）按 upstream
        状态码决定流式转发或同码错误映射；超时/断连 → ServiceUnavailable。
        """
        path = f"/v1/unified/media/{asset_id}/content"
        try:
            return await self._http().get(path, params=params)
        except httpx.TimeoutException as exc:
            raise ServiceUnavailable(
                f"unified memory service timeout (GET {path}): {exc}",
                route=path) from exc
        except httpx.TransportError as exc:
            raise ServiceUnavailable(
                f"unified memory service unreachable (GET {path}): {exc}",
                route=path) from exc

    async def ingest_media(self, *, data: bytes, mime: str,
                           source_refs: list[Any] | None = None,
                           duration_ms: int | None = None, width: int | None = None,
                           height: int | None = None) -> dict:
        """POST /v1/unified/media：原始字节上传（Content-Type = mime）→ asset 回执。"""
        params: dict[str, Any] = {}
        if duration_ms is not None:
            params["duration_ms"] = str(int(duration_ms))
        if width is not None:
            params["width"] = str(int(width))
        if height is not None:
            params["height"] = str(int(height))
        _status, body = await self.call_raw(
            "POST", "/v1/unified/media", content=data, content_type=mime,
            params=params or None)
        return body or {}

    async def get_media(self, asset_id: str) -> dict:
        """GET /v1/unified/media/{asset_id} → 元数据（asset_id + 受控相对路径）。"""
        return await self._request("GET", f"/v1/unified/media/{asset_id}")

    async def delete_media(self, asset_id: str) -> dict:
        """DELETE /v1/unified/media/{asset_id} → 受控删除回执（live 引用 409）。"""
        return await self._request("DELETE", f"/v1/unified/media/{asset_id}")

    # -- 附加读取（§6 表内 GET 路由，UM01 已接线的两个）--

    async def list_records(self, *, facet: str | None = None, status: str | None = None,
                           cursor: str | None = None,
                           limit: int = 50) -> dict:
        """GET /v1/unified/records → items + next_cursor（服务端主体绑定）。"""
        params: dict[str, Any] = {"limit": limit}
        if facet:
            params["facet"] = facet
        if status:
            params["status"] = status
        if cursor:
            params["cursor"] = cursor
        return await self._request("GET", "/v1/unified/records", params=params)

    async def get_record(self, record_ref: str) -> dict:
        """GET /v1/unified/records/{record_ref} → UnifiedRecord（错主体 403 / 404）。"""
        return await self._request("GET", f"/v1/unified/records/{record_ref}")
