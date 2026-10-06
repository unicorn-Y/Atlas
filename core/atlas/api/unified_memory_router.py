"""Unified-memory proxy surface (``/api/unified-memory/*``), T01.3 单一调用路径.

契约（docs/plan/UNIFIED-MEMORY/01_contracts.md §6）：Atlas 代理路径统一
``/api/unified-memory/*``，后缀与 MemoryOS ``/v1/unified/*`` 一一对应；
**UI/API 不直接访问 MemoryOS 数据库或原文件路径** —— 全部读写都经此代理，
由 :class:`~atlas.memory.unified_facade.UnifiedMemoryFacade` 的通用
``call(method, path, json, params)`` 传输到真实 MemoryOS 服务。

* 已接线后缀：observe / recall / records / records/{record_ref} /
  evidence/{record_ref} / status / timeline / entities(+resolve) / corrections /
  sources/change / multimodal/associate（T05.2：确定性关联入口，表驱动透传）/
  media（T05.1：POST 上传与 GET content 为手写透传 —— 原始字节与文件流不落盘
  副本；GET 元数据 / DELETE 走表驱动 JSON 透传）。
* 其余任务书后缀：同样注册并**透传**，由服务端 501 FEATURE_NOT_READY 原样
  透传（后续波在 MemoryOS 侧接线后本代理自动跟随，不需要改这里）。
* 错误映射保持同码：403/404/409/410/413/422/423/501 与超时/断连（503）→
  HTTPException，detail 保留服务端 error code/message/details。

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
    # T05.2 多模态关联：服务端已接线（multimodal.run_association_pass），
    # 表驱动 JSON 透传（候选/等价组原样返回）。
    ("POST", "/multimodal/associate"),
    # T05.1 受控媒体：元数据与删除走通用 JSON 透传；上传（原始字节）与
    # 文件流（不落盘副本）在下方手写（见 proxy_media_upload / proxy_media_content）。
    ("GET", "/media/{asset_id}"),
    ("DELETE", "/media/{asset_id}"),
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


@router.post("/media")
async def proxy_media_upload(
    request: Request,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> JSONResponse:
    """POST /api/unified-memory/media — 受控媒体上传透传（T05.1）。

    body / Content-Type **原样字节转发**到 MemoryOS POST /v1/unified/media
    （JSON b64 或原始字节同语义；Atlas 不做 hash、不落盘副本，去重与白名单
    裁决都在服务端）。同码映射：422 白名单/批次、413 超限、410 已 ERASED。
    """
    body = await request.body()
    content_type = request.headers.get("content-type")
    try:
        status, payload = await _facade(services).client().call_raw(
            "POST", "/v1/unified/media", content=body, content_type=content_type)
    except UnifiedMemoryError as exc:
        raise _http_error(exc) from exc
    return JSONResponse(status_code=status, content=payload)


@router.get("/media/{asset_id}/content")
async def proxy_media_content(
    request: Request,
    asset_id: str,
    services: Annotated[AppServices, Depends(get_app_services)],
) -> Any:
    """GET /api/unified-memory/media/{asset_id}/content — 原媒体文件流透传（T05.1）。

    服务端 lifecycle 校验后的字节流**流式转发**（Atlas 不落盘副本、不解析
    内容）；ERASED / 文件缺失 → 服务端 410 同码透传（显式原因，UI 显示原因，
    不造 caption）。
    """
    from fastapi.responses import StreamingResponse

    client = _facade(services).client()
    response = await client.fetch_media_content(
        asset_id, params=dict(request.query_params))
    if 200 <= response.status_code < 300:
        headers = {}
        for name in ("x-asset-id", "x-asset-relative-path"):
            if response.headers.get(name):
                headers[name] = response.headers[name]
        headers["Cache-Control"] = "no-store"
        return StreamingResponse(
            response.aiter_bytes(), status_code=response.status_code,
            media_type=response.headers.get("content-type", "application/octet-stream"),
            headers=headers)
    detail = response.json() if (response.content and
                                 "json" in response.headers.get("content-type", "")) else {
        "error": "MEDIA_UPSTREAM_ERROR", "message": response.text[:300]}
    raise HTTPException(status_code=response.status_code, detail=detail)


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


# ---------------------------------------------------------------------------
# Atlas 本地采集控制（T05.3 / §6.1）—— capture/start|pause|stop 与 capture/
# status 由 Atlas 本地控制器处理，**不代理** MemoryOS 同名路由；被动采集状态、
# 授权范围与 passive_capture_watermark 是 Atlas 本机事实。pause/stop 只停后台
# 被动观察，不影响正常聊天与主动工具归档（那走 CaptureService/outbox 管线）。
# ---------------------------------------------------------------------------


def _passive_controller() -> Any:
    """取被动采集控制器；capture 未装配（disabled）→ 显式 503（与本地路由一致）。"""
    _windows_sources()  # capture disabled → 503（复用同一装配判据）
    from atlas.memory.windows_sources import get_passive_capture_controller

    return get_passive_capture_controller()


async def _capture_control_body(request: Request, *, sources_required: bool,
                                ) -> tuple[str, Any, list[Any]]:
    """控制请求体解析：request_id 必填、expected_revision 可选、sources 按需。"""
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001 — 非 JSON body → 与 FastAPI 同为 422
        raise HTTPException(status_code=422, detail={
            "error": "INVALID_BODY", "message": "请求体必须是 JSON 对象"}) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=422, detail={
            "error": "INVALID_BODY", "message": "请求体必须是 JSON 对象"})
    request_id = str(body.get("request_id") or "").strip()
    if not request_id:
        raise HTTPException(status_code=422, detail={
            "error": "CAPTURE_REQUEST_ID_REQUIRED",
            "message": "body.request_id 必填（幂等重放键；重试沿用同一 id）"})
    sources = body.get("sources") if sources_required else None
    return request_id, body.get("expected_revision"), sources


def _capture_control_error(exc: Any) -> HTTPException:
    """CaptureControlError → HTTPException 同码（409 冲突 / 422 参数）。"""
    return HTTPException(status_code=int(getattr(exc, "http_status", 409)),
                         detail={"error": exc.code, "message": str(exc),
                                 "details": exc.details})


@router.post("/capture/start")
async def capture_start(request: Request) -> JSONResponse:
    """POST /api/unified-memory/capture/start — 进入 RUNNING（T05.3 / §6.1）。

    body: ``{"request_id": str, "expected_revision"?: int, "sources":
    [{"kind": "window|screen|session|media", "value": str}]}``。sources 是用户
    显式选择的观察入口（无全系统种类 —— 默认不开全系统连续录屏）；隐私门引用
    现有设置（config_refs 回显）。同 request_id 幂等重放；状态版本不符 409。
    """
    request_id, expected_revision, sources = await _capture_control_body(
        request, sources_required=True)
    controller = _passive_controller()
    from atlas.memory.windows_sources import CaptureControlError

    try:
        result = controller.start(request_id, sources,
                                  expected_revision=expected_revision)
    except CaptureControlError as exc:
        raise _capture_control_error(exc) from exc
    return JSONResponse(content=result)


@router.post("/capture/pause")
async def capture_pause(request: Request) -> JSONResponse:
    """POST /api/unified-memory/capture/pause — RUNNING → PAUSED（§6.1）。

    只暂停被动观察入口；正常聊天与主动工具归档照常。在途被动观察先排空
    （或显式记缺口）再报告成功。
    """
    request_id, expected_revision, _ = await _capture_control_body(
        request, sources_required=False)
    controller = _passive_controller()
    from atlas.memory.windows_sources import CaptureControlError

    try:
        result = controller.pause(request_id, expected_revision=expected_revision)
    except CaptureControlError as exc:
        raise _capture_control_error(exc) from exc
    return JSONResponse(content=result)


@router.post("/capture/stop")
async def capture_stop(request: Request) -> JSONResponse:
    """POST /api/unified-memory/capture/stop — → STOPPED（§6.1）。

    从 STOPPED 直接 stop 是幂等成功（already_stopped，revision 不推进）；
    迁移时在途被动观察先完成（或显式记 gaps）再报告成功。停止后被动水位
    不再前进，但普通工具截图仍正常记入工具经历（本路由不触碰那条管线）。
    """
    request_id, expected_revision, _ = await _capture_control_body(
        request, sources_required=False)
    controller = _passive_controller()
    from atlas.memory.windows_sources import CaptureControlError

    try:
        result = controller.stop(request_id, expected_revision=expected_revision)
    except CaptureControlError as exc:
        raise _capture_control_error(exc) from exc
    return JSONResponse(content=result)


@router.get("/capture/status")
async def capture_status() -> JSONResponse:
    """GET /api/unified-memory/capture/status — 被动采集状态与三分水位（§6.1）。

    返回 state/revision/passive_capture_watermark/last_error/sources 与
    watermarks（conversation/tool/passive 三分开 —— **不能**用总水位判断被动
    采集已停止）。collector 块如实标注当前采集能力边界（后台连续截屏未实现，
    偏差 PARTIAL）。
    """
    controller = _passive_controller()
    from atlas.memory import windows_sources

    payload = controller.status()
    payload["watermarks"] = {
        "conversation": {}, "tool": {},
        "passive": {"captured": int(payload["passive_capture_watermark"]),
                    "gaps": len(payload.get("gaps") or [])},
    }
    counts = windows_sources.capture_watermarks()
    payload["watermarks"]["conversation"] = counts["buckets"]["conversation"]
    payload["watermarks"]["tool"] = counts["buckets"]["tool"]
    if counts.get("error"):
        payload["watermarks"]["error"] = counts["error"]
    payload["collector"] = {
        "background_polling": "PARTIAL_NOT_IMPLEMENTED",
        "entry": "x2_tool_receipt",
        "note": "当前 Atlas 无后台连续截屏/标题轮询能力；被动入口只记录选择"
                "范围内真实到达的 x2 工具收据，不假装在录，不可见后台应用不"
                "声称已记住（T05.3 偏差记录，真实后台采集留后续波）",
    }
    return JSONResponse(content=payload)
