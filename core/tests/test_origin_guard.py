"""Browser requests from foreign origins must not reach the Atlas backend."""

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from atlas.origin_guard import OriginGuard, is_trusted

EVIL = "https://evil.example"
DEV = "http://127.0.0.1:5173"


async def _ok(request):
    return PlainTextResponse("ok")


async def _ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_text("hello")
    await websocket.close()


def _guarded_app(extra=()):
    app = Starlette(routes=[
        Route("/ping", _ok, methods=["GET", "POST"]), WebSocketRoute("/ws", _ws),
    ])
    app.add_middleware(OriginGuard, extra_origins=lambda: extra)
    return app


@pytest.fixture
def token(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", "launch-secret")
    return "launch-secret"


def test_is_trusted_rules(token):
    assert is_trusted(None, None)
    assert is_trusted(DEV, None)
    assert is_trusted("https://atlas.internal", None, ["https://atlas.internal"])
    assert not is_trusted(EVIL, None)
    # file:// pages and sandboxed iframes on any site both send "null".
    assert not is_trusted("null", None)
    assert not is_trusted("null", "wrong")
    assert is_trusted("null", token)
    assert is_trusted(EVIL, token)


def test_same_origin_browser_requests_need_the_token(token):
    """A page the backend served itself (a previewed file) must not read the API."""
    assert not is_trusted(None, None, fetch_site="same-origin")
    assert is_trusted(None, token, fetch_site="same-origin")
    # The Vite dev page is same-site (different port), the packaged file:// page cross-site.
    assert is_trusted(DEV, None, fetch_site="same-site")
    assert is_trusted(None, None, fetch_site=None)


def test_null_origin_is_rejected_when_no_token_is_configured(monkeypatch):
    monkeypatch.delenv("ATLAS_API_TOKEN", raising=False)
    assert not is_trusted("null", "")
    assert not is_trusted("null", "anything")


def test_http_requests_from_foreign_origins_are_refused(token):
    client = TestClient(_guarded_app())
    assert client.get("/ping").status_code == 200
    assert client.get("/ping", headers={"Origin": DEV}).status_code == 200
    assert client.post("/ping", headers={"Origin": EVIL}, content="x").status_code == 403
    assert client.get("/ping", headers={"Origin": "null"}).status_code == 403
    with_token = {"Origin": "null", "X-Atlas-Api-Token": token}
    assert client.get("/ping", headers=with_token).status_code == 200


def test_websockets_from_foreign_origins_are_closed_before_accept(token):
    client = TestClient(_guarded_app())
    with client.websocket_connect("/ws", headers={"Origin": DEV}) as ws:
        assert ws.receive_text() == "hello"
    with_token = {"Origin": "null", "X-Atlas-Api-Token": token}
    with client.websocket_connect("/ws", headers=with_token) as ws:
        assert ws.receive_text() == "hello"
    for headers in ({"Origin": EVIL}, {"Origin": "null"}):
        with pytest.raises(WebSocketDisconnect) as closed:
            with client.websocket_connect("/ws", headers=headers):
                pass
        assert closed.value.code == 1008


def test_configured_origins_are_allowed():
    client = TestClient(_guarded_app(extra=["https://atlas.internal"]))
    assert client.get("/ping", headers={"Origin": "https://atlas.internal"}).status_code == 200


@pytest.mark.asyncio
async def test_atlas_backend_applies_the_guard_to_every_route():
    """The real app refuses a foreign origin before routing, so no lifespan is needed."""
    from atlas.server import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        refused = await client.get("/api/health", headers={"Origin": EVIL})
        assert refused.status_code == 403
        assert "access-control-allow-origin" not in refused.headers
        preflight = await client.options("/api/conversations", headers={
            "Origin": EVIL, "Access-Control-Request-Method": "POST",
        })
        assert preflight.headers.get("access-control-allow-origin") is None
        allowed = await client.options("/api/conversations", headers={
            "Origin": DEV, "Access-Control-Request-Method": "POST",
        })
        assert allowed.headers.get("access-control-allow-origin") == DEV


@pytest.mark.asyncio
async def test_external_agent_status_endpoint_uses_origin_guard(monkeypatch):
    from atlas import server
    from atlas.server import app

    monkeypatch.setattr(server, "external_agent_status", lambda _cache: {"agents": []})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.get("/api/agents/external", headers={"Origin": DEV})
        refused = await client.get(
            "/api/agents/external", headers={"Sec-Fetch-Site": "same-origin"},
        )
        token_access = await client.get("/api/agents/external", headers={
            "Origin": "null", "X-Atlas-Api-Token": "test-atlas-api-token",
        })
    assert allowed.status_code == 200
    assert refused.status_code == 403
    assert token_access.status_code == 200


@pytest.mark.asyncio
async def test_previewed_workspace_html_is_sandboxed(tmp_path):
    """Raw HTML from a workspace gets an opaque origin, so its scripts can't call the API."""
    from atlas.server import app

    page = "<script>fetch('/api/conversations')</script>"
    (tmp_path / "page.html").write_text(page, encoding="utf-8")
    (tmp_path / "doc.pdf").write_bytes(b"%PDF-1.4")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        raw = {"root": str(tmp_path)}
        html = await client.get("/api/workspace/raw", params={**raw, "path": "page.html"})
        pdf = await client.get("/api/workspace/raw", params={**raw, "path": "doc.pdf"})
        from_page = await client.get("/api/conversations",
                                     headers={"Sec-Fetch-Site": "same-origin"})
    assert html.status_code == 200
    assert html.headers["content-security-policy"].startswith("sandbox")
    assert html.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in pdf.headers
    assert from_page.status_code == 403


@pytest.mark.asyncio
async def test_office_preview_route_uses_origin_guard(tmp_path, monkeypatch):
    from atlas.office import create_document
    from atlas.server import app

    create_document(str(tmp_path), {
        "path": "preview.docx", "blocks": [{"type": "paragraph", "text": "safe"}],
    })
    monkeypatch.setenv("ATLAS_API_TOKEN", "test-atlas-api-token")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.get("/api/workspace/preview", params={
            "root": str(tmp_path), "path": "preview.docx",
        }, headers={"Origin": EVIL})
        allowed = await client.get("/api/workspace/preview", params={
            "root": str(tmp_path), "path": "preview.docx",
        }, headers={"Origin": "null", "X-Atlas-Api-Token": "test-atlas-api-token"})
    assert denied.status_code == 403
    assert allowed.status_code == 200
    assert "content-security-policy" in allowed.headers


def test_hub_control_api_refuses_web_pages():
    from atlas.runtime.hub import create_hub_app

    client = TestClient(create_hub_app())
    assert client.get("/health").status_code == 200
    assert client.post("/shutdown", headers={"Origin": EVIL}).status_code == 403
    assert client.post("/tasks/any/run", headers={"Origin": "null"}).status_code == 403
