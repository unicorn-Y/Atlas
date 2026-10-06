"""Unified-memory proxy surface (``/api/unified-memory/*``), T01.3 单一调用路径.

契约（docs/plan/UNIFIED-MEMORY/01_contracts.md §6）：Atlas 代理路径统一
``/api/unified-memory/*``，后缀与 MemoryOS ``/v1/unified/*`` 一一对应；
**UI/API 不直接访问 MemoryOS 数据库或原文件路径** —— 全部读写都经此代理，
由 :class:`~atlas.memory.unified_facade.UnifiedMemoryFacade` 的通用
``call(method, path, json, params)`` 传输到真实 MemoryOS 服务。

* 已接线后缀：observe / recall / records / records/{record_ref} /
  evidence/{record_ref} / status。
* 其余任务书后缀：同样注册并**透传**，由服务端 501 FEATURE_NOT_READY 原样
  透传（后续波在 MemoryOS 侧接线后本代理自动跟随，不需要改这里）。
* 错误映射保持同码：403/409/423/422/501 与超时/断连（503）→ HTTPException，
  detail 保留服务端 error code/message/details。

挂载方式：本 router 仅在 ``memory.unified.enabled=true`` 时由
``atlas.api.application.create_app`` include（默认 false → 完全不挂，
既有测试与共享 app 守卫零影响）。
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from starlette.requests import Request

from atlas.api.app_services import AppServices
from atlas.api.dependencies import get_app_services
from atlas.memory.capture import ContentTooLarge
from atlas.memory.windows_sources import ImportTooManySegments, ImportUnsupported
from atlas.memory.unified_client import (
    ContractViolation,
    ErasureBlocked,
    FeatureNotReady,
    ForbiddenSubject,
    RevisionConflict,
    ServiceUnavailable,
    UnifiedMemoryError,
)

router = APIRouter(prefix="/api/unified-memory", tags=["UnifiedMemoryProxy"])

#: 与 MemoryOS service/unified/api.py 的路由面一一对应（§6 路由表）。
#: 前六个是 T01.1 已接线的真实路由；其余透传 501（服务端未接线）。
PROXY_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/observe"),
    ("POST", "/recall"),
    ("GET", "/records"),
    ("GET", "/records/{record_ref:path}"),
    ("GET", "/evidence/{record_ref:path}"),
    ("GET", "/status"),
    # 未接线路由：透传 → 服务端 501 FEATURE_NOT_READY（保留 route）
    ("POST", "/corrections"),
    ("POST", "/sources/change"),
    ("POST", "/focus"),
    ("POST", "/intents"),
    ("GET", "/intents"),
    ("POST", "/intents/{intent_id}/transition"),
    ("POST", "/outcomes"),
    ("POST", "/feedback"),
    ("POST", "/applications"),
    ("POST", "/dependencies/check"),
    ("GET", "/learning"),
    ("POST", "/maintenance"),
    ("POST", "/export"),
    ("GET", "/timeline"),
    ("GET", "/entities"),
    ("POST", "/entities/resolve"),
)

#: 客户端错误类 → HTTP 同码（status_code 为 None 的传输类错误回落 503）。
_ERROR_STATUS: dict[type[UnifiedMemoryError], int] = {
    FeatureNotReady: 501,
    RevisionConflict: 409,
    ErasureBlocked: 423,
    ForbiddenSubject: 403,
    ContractViolation: 422,
    ServiceUnavailable: 503,
}


def _http_error(exc: UnifiedMemoryError) -> HTTPException:
    """UnifiedMemoryError → HTTPException 同码；detail 保留服务端错误体。"""
    status = exc.status_code or _ERROR_STATUS.get(type(exc), 502)
    return HTTPException(status_code=status, detail={
        "error": exc.code or type(exc).__name__,
        "message": str(exc),
        "details": exc.detail if isinstance(exc.detail, (dict, list)) else exc.detail,
        "route": exc.route,
    })


def _facade(services: AppServices) -> Any:
    facade = services.unified_memory
    if facade is None:
        # 路由只在 enabled=true 时挂载；无 facade 说明 lifespan 没装配 —— 配置
        # 与服务状态不一致，显式报错而不是静默 404/空响应。
        raise HTTPException(status_code=503, detail={
            "error": "UNIFIED_MEMORY_NOT_COMPOSED",
            "message": "unified-memory proxy route mounted but no facade is "
                       "composed in this app's services",
        })
    return facade


#: 路径参数占位（含 FastAPI 转换器，如 ``{record_ref:path}``）
_PATH_PARAM_RE = re.compile(r"\{(\w+)(?::[^}]+)?\}")


def _make_proxy(method: str, suffix: str):
    """为一个 (method, suffix) 生成透传端点：body/query/path 原样转发，JSON 返回。"""

    async def endpoint(
        request: Request,
        services: Annotated[AppServices, Depends(get_app_services)],
    ) -> Any:
        upstream = _PATH_PARAM_RE.sub(
            lambda match: str(request.path_params.get(match.group(1), "")), suffix)
        body: Any = None
        if method == "POST":
            body = await request.json()
        try:
            result = await _facade(services).call(
                method, f"/v1/unified{upstream}", json=body,
                params=dict(request.query_params))
        except UnifiedMemoryError as exc:
            raise _http_error(exc) from exc
        return JSONResponse(content=result)

    endpoint.__name__ = f"proxy_{method.lower()}_{suffix.strip('/')}"
    endpoint.__doc__ = (
        f"T01.3 proxy: {method} /api/unified-memory{suffix} → "
        f"{method} /v1/unified{suffix}（MemoryOS 同码透传）。"
    )
    return endpoint


for _method, _suffix in PROXY_ROUTES:
    router.add_api_route(
        _suffix, _make_proxy(_method, _suffix), methods=[_method],
        name=f"unified_memory_proxy_{_method.lower()}_"
             f"{_suffix.strip('/').replace('/', '_').replace('{', '').replace('}', '').replace(':', '_')}",
        include_in_schema=True,
    )


# ---------------------------------------------------------------------------
# Atlas 本地路由（T02.3）—— 与 §6.1 的 capture/start|pause|stop 同类：不代理
# MemoryOS，由 Atlas 本地采集控制器（WindowsSourceService → CaptureService →
# outbox）处理；观察随后经既有 flush 管线落统一记忆服务。
# ---------------------------------------------------------------------------


def _windows_sources() -> Any:
    """取 WindowsSourceService；capture 未启用（disabled/未装配）→ 显式 503。"""
    from atlas.memory.windows_sources import get_windows_source_service

    service = get_windows_source_service()
    if service is None:
        raise HTTPException(status_code=503, detail={
            "error": "CAPTURE_NOT_COMPOSED",
            "message": "unified memory capture is disabled "
                       "(memory.unified.enabled/capture_mode)",
        })
    return service


@router.post("/import")
async def import_text_file(request: Request) -> JSONResponse:
    """POST /api/unified-memory/import — 本地 txt/md/json/pdf 文本导入（T02.3）。

    body: ``{"path": str, "root"?: str, "task_id"?: str}``；走真实文件系统读取
    （UI 不直接访问原文件路径的边界由调用方/UI 层保证 —— 本路由是 Atlas 本机
    导入入口，返回观察批次入库回执：created/duplicates/revision/locator）。
    幂等：同 hash 重导 created=0；内容修改新 revision；移动不制造新事实。
    """
    body = await request.json()
    path = str(body.get("path") or "").strip()
    if not path:
        raise HTTPException(status_code=422, detail={
            "error": "IMPORT_PATH_REQUIRED", "message": "body.path 必填"})
    root = str(body.get("root") or "").strip() or None
    task_id = str(body.get("task_id") or "").strip() or None
    service = _windows_sources()
    try:
        result = service.import_text_file(path, task_id=task_id, root=root)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail={
            "error": "IMPORT_FILE_NOT_FOUND", "message": str(exc)}) from exc
    except IsADirectoryError as exc:
        raise HTTPException(status_code=422, detail={
            "error": "IMPORT_NOT_A_FILE", "message": str(exc)}) from exc
    except ContentTooLarge as exc:
        # §2 超限：显式 CONTENT_TOO_LARGE（T02.1 服务端语义），不静默截断。
        raise HTTPException(status_code=413, detail={
            "error": "CONTENT_TOO_LARGE", "message": str(exc),
            "size_bytes": exc.size_bytes}) from exc
    except ImportUnsupported as exc:
        raise HTTPException(status_code=415, detail={
            "error": exc.code, "message": str(exc), "details": exc.details}) from exc
    except ImportTooManySegments as exc:
        raise HTTPException(status_code=413, detail={
            "error": exc.code, "message": str(exc),
            "segments": exc.count, "limit": exc.limit}) from exc
    return JSONResponse(content=result)


@router.post("/verify-agent-result")
async def verify_agent_result(request: Request) -> JSONResponse:
    """POST /api/unified-memory/verify-agent-result — Atlas 独立验证追加（T02.3）。

    body: ``{"tool_call_id": str, "checks": [{"kind","target","passed","detail"...}],
    "session_id"?: str, "tool_name"?: str}``。checks 必须来自 Atlas 自己的真实
    检查（文件存在/真实产物/可观察结果）—— 被调 Agent 的自报声明**不是验证**；
    追加 ATLAS_VERIFICATION 观察（同一 source_object_id，revision=3）。
    episode outcome 更新留 UM09。
    """
    body = await request.json()
    tool_call_id = str(body.get("tool_call_id") or "").strip()
    checks = body.get("checks")
    if not tool_call_id:
        raise HTTPException(status_code=422, detail={
            "error": "TOOL_CALL_ID_REQUIRED", "message": "body.tool_call_id 必填"})
    if not isinstance(checks, list) or not checks:
        raise HTTPException(status_code=422, detail={
            "error": "CHECKS_REQUIRED",
            "message": "body.checks 必须是非空数组（无真实检查不产生验证观察）"})
    service = _windows_sources()
    result = service.verify_agent_result(
        tool_call_id, [item for item in checks if isinstance(item, dict)],
        session_id=str(body.get("session_id") or "").strip() or None,
        tool_name=str(body.get("tool_name") or "agent"))
    if result is None:
        raise HTTPException(status_code=422, detail={
            "error": "VERIFICATION_NOT_RECORDED",
            "message": "tool_call_id / session_id 无法构成稳定观察对象"})
    return JSONResponse(content=result)
