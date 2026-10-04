"""Freeze the HTTP and WebSocket surface before the server split."""

from __future__ import annotations

import ast
import fastapi
import inspect
import json
import re
import pytest
from pathlib import Path
from typing import Any

from fastapi import WebSocket
from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute


ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas"
SNAPSHOT = Path(__file__).parent / "snapshots" / "routes.json"
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put"}


class _RouteView:
    """An effective FastAPI route context with its prefix-adjusted path."""

    def __init__(self, route: Any, path: str) -> None:
        self.route = route
        self.path = path

    def __getattr__(self, name: str) -> Any:
        return getattr(self.route, name)


def _json_schema(value: Any) -> Any:
    """Return JSON-compatible OpenAPI material with deterministic dict order."""
    if isinstance(value, dict):
        return {key: _json_schema(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_json_schema(item) for item in value]
    return value


def _parameter_schema(field: Any) -> dict[str, Any]:
    field_info = field.field_info
    annotation = getattr(field, "annotation", None) or getattr(field, "type_", None)
    required_check = getattr(field_info, "is_required", None)
    required = required_check() if callable(required_check) else getattr(field, "required", None)
    if required is None:
        required_check = getattr(field, "is_required", None)
        required = required_check() if callable(required_check) else field.default is Ellipsis
    default = None if required else field.default
    if default is not None and not isinstance(default, (str, int, float, bool, list, dict)):
        default = repr(default)
    return {
        "name": field.name,
        "in": getattr(getattr(field_info, "in_", None), "value", None) or "query",
        "required": bool(required),
        "type": getattr(annotation, "__name__", str(annotation)),
        "default": default,
    }


def _incoming_websocket_types(tree: ast.Module, function_name: str) -> list[str]:
    function = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == function_name
    )
    found: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        names = [node.left, *node.comparators]
        compares_type_field = any(
            isinstance(item, ast.Call)
            and isinstance(item.func, ast.Attribute)
            and item.func.attr == "get"
            and item.args
            and isinstance(item.args[0], ast.Constant)
            and item.args[0].value == "type"
            for item in names
        )
        compares_type_name = any(
            isinstance(item, ast.Name) and item.id in {"msg_type", "event_type"}
            for item in names
        )
        if not (compares_type_field or compares_type_name):
            continue
        found.update(
            item.value for item in names
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
    return sorted(found)


def _source_tree(atlas_root: Path = ATLAS) -> ast.Module:
    """Read the current implementation modules, so moved protocol code stays visible."""
    modules = [
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for path in sorted(atlas_root.rglob("*.py"))
    ]
    return ast.Module(body=[node for module in modules for node in module.body], type_ignores=[])


def _outgoing_websocket_types(tree: ast.Module, endpoint: Any) -> list[str]:
    """Collect emitted event names from the endpoint module and runtime mapper seams."""
    found: set[str] = set()
    source = ast.parse(inspect.getsource(endpoint))
    for node in ast.walk(source):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "send_json" or not node.args or not isinstance(node.args[0], ast.Dict):
            continue
        for key, value in zip(node.args[0].keys, node.args[0].values):
            if (isinstance(key, ast.Constant) and key.value == "type"
                    and isinstance(value, ast.Constant) and isinstance(value.value, str)):
                found.add(value.value)
    if getattr(endpoint, "__name__", "") != "ws_chat":
        return sorted(found)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else (
            node.func.attr if isinstance(node.func, ast.Attribute) else ""
        )
        if name not in {"emit", "next_envelope"} or not node.args:
            continue
        value = node.args[0]
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            found.add(value.value)
    for function in tree.body:
        if (not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef))
                or "map" not in function.name or "event" not in function.name):
            continue
        for candidate in ast.walk(function):
            if (isinstance(candidate, ast.Return) and isinstance(candidate.value, ast.Tuple)
                    and candidate.value.elts
                    and isinstance(candidate.value.elts[0], ast.Constant)
                    and isinstance(candidate.value.elts[0].value, str)):
                found.add(candidate.value.elts[0].value)
    return sorted(found)


def _flatten_routes(routes: list[Any]) -> list[Any]:
    """Expand FastAPI lazy includes to their effective paths in match order."""
    flattened: list[Any] = []

    def join_path(prefix: str, path: str) -> str:
        return f"{prefix.rstrip('/')}/{path.lstrip('/')}" if prefix else path

    def route_paths(router: Any, prefix: str = "") -> list[tuple[Any, str]]:
        mounted: list[tuple[Any, str]] = []
        for child in getattr(router, "routes", ()):
            child_context = getattr(child, "include_context", None)
            child_router = getattr(child, "original_router", None)
            if child_router is not None and child_context is not None:
                mounted.extend(route_paths(
                    child_router, join_path(prefix, child_context.prefix),
                ))
            else:
                mounted.append((child, join_path(prefix, getattr(child, "path", ""))))
        return mounted

    def visit(route: Any) -> None:
        if isinstance(route, (APIRoute, WebSocketRoute)):
            flattened.append(route)
            return
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_contexts):
            # FastAPI supplies effective parameter contexts. Its WebSocket
            # contexts currently lack .path, so correlate them with the router's
            # inclusion tree rather than dropping prefixes or using a constant.
            context = getattr(route, "include_context", None)
            prefix = getattr(context, "prefix", "") or ""
            mounted_paths: dict[int, list[str]] = {}
            for original, path in route_paths(getattr(route, "original_router", None), prefix):
                mounted_paths.setdefault(id(original), []).append(path)
            for context in effective_contexts():
                path = getattr(context, "path", "") or getattr(context, "path_format", "")
                if not path:
                    original = getattr(context, "original_route", None)
                    candidates = mounted_paths.get(id(original), [])
                    path = candidates.pop(0) if candidates else join_path(
                        prefix, getattr(original, "path", ""),
                    )
                flattened.append(_RouteView(context, path))
            return
        nested = getattr(route, "routes", None)
        if nested is None:
            nested = getattr(getattr(route, "router", None), "routes", None)
        if nested is None:
            nested = getattr(getattr(route, "original_router", None), "routes", None)
        if nested:
            for child in nested:
                visit(child)

    for route in routes:
        visit(route)
    return flattened


def _is_http_route(route: Any) -> bool:
    return isinstance(route, APIRoute) or isinstance(
        getattr(route, "original_route", None), APIRoute,
    )


def _is_websocket_route(route: Any) -> bool:
    return isinstance(route, WebSocketRoute) or isinstance(
        getattr(route, "original_route", None), WebSocketRoute,
    )


def _field_model_name(field: Any) -> str | None:
    if field is None:
        return None
    type_ = getattr(field, "type_", None) or getattr(field, "annotation", None)
    return getattr(type_, "__name__", str(type_))


def _effective_attr(route: Any, name: str) -> Any:
    value = getattr(route, name, None)
    if value is not None:
        return value
    return getattr(getattr(route, "original_route", None), name, None)


def _effective_path(route: Any) -> str:
    if isinstance(route, _RouteView):
        return route.path
    path = getattr(route, "path", "")
    return path or getattr(getattr(route, "original_route", None), "path", "")


def _path_patterns_overlap(left: str, right: str) -> bool:
    left_parts = left.strip("/").split("/")
    right_parts = right.strip("/").split("/")
    if len(left_parts) != len(right_parts):
        return False
    for left_part, right_part in zip(left_parts, right_parts):
        left_dynamic = left_part.startswith("{") and left_part.endswith("}")
        right_dynamic = right_part.startswith("{") and right_part.endswith("}")
        if not left_dynamic and not right_dynamic and left_part != right_part:
            return False
    return left != right


def _shadow_order(routes: list[Any]) -> list[dict[str, str]]:
    """Preserve only relative order for same-method routes that can collide."""
    ordered: list[tuple[str, str]] = []
    for route in routes:
        if not _is_http_route(route):
            continue
        for method in sorted(route.methods or set()):
            ordered.append((method, _effective_path(route)))
    overlaps: list[dict[str, str]] = []
    for index, (method, path) in enumerate(ordered):
        for other_method, other_path in ordered[index + 1:]:
            if method == other_method and _path_patterns_overlap(path, other_path):
                overlaps.append({"method": method, "earlier": path, "later": other_path})
    return overlaps


def build_route_snapshot(atlas_root: Path = ATLAS) -> dict[str, Any]:
    """Capture registered routes, parameter/model schemas, and WS protocol types."""
    from atlas import server

    atlas_root = atlas_root.resolve()
    app = server.app

    openapi = app.openapi()
    tree = _source_tree(atlas_root)
    routes: list[dict[str, Any]] = []
    ordered_routes = _flatten_routes(app.routes)
    for route in ordered_routes:
        if _is_http_route(route):
            operations = []
            for method in sorted(route.methods or set()):
                if method.lower() not in HTTP_METHODS:
                    continue
                path = _effective_path(route)
                operation = openapi.get("paths", {}).get(path, {}).get(method.lower())
                if operation is not None:
                    operations.append({
                        "method": method,
                        "operation_id": operation.get("operationId"),
                        "parameters": _json_schema(operation.get("parameters", [])),
                        "request_body": _json_schema(operation.get("requestBody")),
                        "responses": _json_schema(operation.get("responses", {})),
                    })
                else:
                    operations.append({
                        "method": method,
                        "include_in_schema": False,
                        "parameters": [
                            _parameter_schema(field)
                            for field in [
                                *_effective_attr(route, "dependant").path_params,
                                *_effective_attr(route, "dependant").query_params,
                                *_effective_attr(route, "dependant").header_params,
                                *_effective_attr(route, "dependant").cookie_params,
                            ]
                        ],
                        "request_body_model": _field_model_name(_effective_attr(route, "body_field")),
                        "response_model": _field_model_name(_effective_attr(route, "response_field")),
                    })
            routes.append({"path": _effective_path(route), "operations": operations})
        elif _is_websocket_route(route):
            parameters = [
                _parameter_schema(field)
                for field in [
                    *_effective_attr(route, "dependant").path_params,
                    *_effective_attr(route, "dependant").query_params,
                    *_effective_attr(route, "dependant").header_params,
                    *_effective_attr(route, "dependant").cookie_params,
                ]
            ]
            protocol: dict[str, Any] = {"parameters": parameters}
            endpoint = _effective_attr(route, "endpoint")
            endpoint_tree = ast.parse(inspect.getsource(endpoint))
            endpoint_name = endpoint.__name__
            protocol["client_event_types"] = _incoming_websocket_types(
                endpoint_tree, endpoint_name,
            )
            protocol["server_event_types"] = _outgoing_websocket_types(tree, endpoint)
            routes.append({
                "path": _effective_path(route),
                "operations": [{"method": "WEBSOCKET", **protocol}],
            })

    routes.sort(key=lambda item: (item["path"], tuple(op["method"] for op in item["operations"])))

    return {
        "build": {
            "server_source": str(Path(server.__file__).resolve().relative_to(atlas_root.parent)),
            "fastapi_version": fastapi.__version__,
        },
        "routes": routes,
        "shadow_order": _shadow_order(ordered_routes),
        "components": _json_schema(openapi.get("components", {})),
    }


def test_routes_match_frozen_snapshot() -> None:
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert build_route_snapshot() == expected


def test_fastapi_lazy_includes_preserve_effective_paths_parameters_and_order() -> None:
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect

    source = APIRouter()

    @source.get("/items/{item_id}")
    async def item(item_id: str, filter: str | None = None) -> dict[str, str | None]:
        return {"item_id": item_id, "filter": filter}

    @source.get("/hidden", include_in_schema=False)
    async def hidden() -> dict[str, bool]:
        return {"hidden": True}

    @source.websocket("/ws/{session_id}")
    async def socket(websocket: WebSocket, session_id: str, token: str) -> None:
        await websocket.accept()
        await websocket.send_json({"session_id": session_id, "token": token})
        await websocket.close()

    nested = APIRouter()
    nested.include_router(source, prefix="/nested")
    app = FastAPI()
    app.include_router(source, prefix="/v1")
    app.include_router(source, prefix="/v2")
    app.include_router(nested, prefix="/api")
    app.openapi()

    routes = _flatten_routes(app.routes)
    http_paths = [_effective_path(route) for route in routes if _is_http_route(route)]
    ws_routes = [route for route in routes if _is_websocket_route(route)]

    assert http_paths == [
        "/v1/items/{item_id}", "/v1/hidden",
        "/v2/items/{item_id}", "/v2/hidden",
        "/api/nested/items/{item_id}", "/api/nested/hidden",
    ]
    assert [_effective_path(route) for route in ws_routes] == [
        "/v1/ws/{session_id}", "/v2/ws/{session_id}", "/api/nested/ws/{session_id}",
    ]
    route = next(route for route in ws_routes if _effective_path(route) == "/v2/ws/{session_id}")
    assert route.original_route.path == "/ws/{session_id}"
    fields = route.original_route.dependant.query_params
    assert [(field.name, _parameter_schema(field)["required"]) for field in fields] == [("token", True)]
    hidden_routes = [route for route in routes if not route.include_in_schema]
    assert [_effective_path(route) for route in hidden_routes] == [
        "/v1/hidden", "/v2/hidden", "/api/nested/hidden",
    ]
    with TestClient(app).websocket_connect("/v2/ws/session-2?token=secret") as websocket:
        assert websocket.receive_json() == {"session_id": "session-2", "token": "secret"}
    with TestClient(app).websocket_connect("/api/nested/ws/session-3?token=secret") as websocket:
        assert websocket.receive_json() == {"session_id": "session-3", "token": "secret"}
    with pytest.raises(WebSocketDisconnect):
        with TestClient(app).websocket_connect("/v2/ws/session-4") as websocket:
            websocket.receive_json()


if __name__ == "__main__":
    import os
    import tempfile

    # Keep the one-time baseline generation from creating config/atlas.toml in
    # the repository when the app module is imported outside the test harness.
    os.environ.setdefault(
        "ATLAS_ROOT", str(Path(tempfile.gettempdir()) / "atlas-route-snapshot-root"),
    )
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(
        json.dumps(build_route_snapshot(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

