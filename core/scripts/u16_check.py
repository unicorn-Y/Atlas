"""U16 checks: offline OSV audit, project roots, model routing, egress and llama.cpp health."""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from atlas.models.router import RouteSpec, _openai_payload
from atlas.projects import ProjectStore
from atlas.security_audit import audit


async def check_project_roots() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        main = root / "main"
        addon = root / "addon"
        main.mkdir(); addon.mkdir()
        store = ProjectStore(root / "projects.db")
        await store.init()
        project = await store.create_project("multi-root", str(main), workspace_paths=[str(addon)])
        await store.attach_conversation(project.project_id, "u16-conversation")
        loaded = await store.find_by_conversation("u16-conversation")
        assert loaded is not None and loaded.workspace_path == str(main)
        assert loaded.workspace_paths == [str(addon)]
        await store.update_project(project.project_id, workspace_paths=[])
        assert (await store.get(project.project_id)).workspace_paths == []
        await store.close()


def check_audit_snapshot() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "core").mkdir(); (root / "frontend").mkdir(); (root / "config").mkdir(); (root / "data").mkdir()
        (root / "core" / "uv.lock").write_text('[[package]]\nname = "demo"\nversion = "1.2.3"\n', encoding="utf-8")
        (root / "frontend" / "package-lock.json").write_text(json.dumps({"packages": {"": {}, "node_modules/pkg": {"name": "pkg", "version": "2.0.0"}}}), encoding="utf-8")
        (root / "config" / "atlas.toml").write_text('[models.gateway]\napi_key = "U16_SECRET_SENTINEL"\n[server]\nhost = "0.0.0.0"\n', encoding="utf-8")
        cache = root / "osv.json"
        cache.write_text(json.dumps({"schema_version": 1, "source": "https://api.osv.dev/v1/querybatch", "updated_at": "2026-10-24T00:00:00+00:00", "results": {
            "PyPI|demo|1.2.3": [{"id": "OSV-DEMO-1", "aliases": ["CVE-2099-1234"]}],
            "npm|pkg|2.0.0": [],
        }}), encoding="utf-8")
        report = audit(root, cache)
        assert report["dependency_count"] == 2 and report["indexed_dependency_count"] == 2
        assert any(row["id"] == "CVE-2099-1234" and row["version"] == "1.2.3" and row["file"] == "core/uv.lock" for row in report["findings"])
        assert any(row["id"] == "ATLAS-CONFIG-PLAINTEXT-SECRET" for row in report["findings"])
        assert "U16_SECRET_SENTINEL" not in json.dumps(report)


def check_service_tier_payload() -> None:
    route = RouteSpec(provider="openai", api_mode="chat_completions", model="openai/demo", base_url="https://api.example.test/v1",
                      wire_model="demo", capabilities={"service_tiers": ["default", "priority"]})
    payload = _openai_payload(route, [{"role": "user", "content": "ping"}], {"service_tier": "priority"})
    assert payload["service_tier"] == "priority"


def check_llama_health() -> None:
    from atlas.api import local_models_router

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200 if self.path == "/health" else 404)
            self.end_headers()
        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    original = local_models_router._llama_config
    try:
        local_models_router._llama_config = lambda: {"port": server.server_port, "binary_path": "", "model_path": ""}
        status = local_models_router._llama_status()
        assert status["healthy"] and status["running"] and not status["managed"]
    finally:
        local_models_router._llama_config = original
        server.shutdown(); server.server_close(); thread.join(timeout=3)


def check_egress_probe() -> None:
    from atlas.api import network_settings_router

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"ip":"203.0.113.7"}'
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    original_url, original_settings = network_settings_router._EGRESS_PROBE_URL, network_settings_router.load_user_settings
    try:
        network_settings_router._EGRESS_PROBE_URL = f"http://127.0.0.1:{server.server_port}/probe"
        network_settings_router.load_user_settings = lambda: {"model_network": {"tool_egress": {"web_search": "direct"}}}
        result = network_settings_router.probe_tool_egress({"tool": "web_search"})
        assert result == {"tool": "web_search", "mode": "direct", "ok": True, "public_ip": "203.0.113.7"}
    finally:
        network_settings_router._EGRESS_PROBE_URL = original_url
        network_settings_router.load_user_settings = original_settings
        server.shutdown(); server.server_close(); thread.join(timeout=3)


async def check_live_model() -> None:
    """Exercise the configured real model route without printing or inspecting credentials."""
    from atlas.models import ModelManager

    response = await ModelManager().model_router.complete_for(
        "deepseek-v4.1-flash", "advisor", [{"role": "user", "content": "Reply with exactly: U16 model reachable"}],
        max_tokens=40, temperature=0,
    )
    assert response.text.strip(), "live model returned an empty answer"


async def main() -> None:
    await check_project_roots()
    check_audit_snapshot()
    check_service_tier_payload()
    check_llama_health()
    check_egress_probe()
    await check_live_model()
    print("U16 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
