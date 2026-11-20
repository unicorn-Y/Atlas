"""Benchmark-only uvicorn runner with an explicit private shutdown control."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import uvicorn


async def _serve(port: int, shutdown_file: Path) -> None:
    from atlas.server import app

    @app.get("/__bench/model-route")
    async def _model_route_diagnostic() -> dict[str, object]:
        services = app.state.services
        manager = getattr(services, "model_mgr", None)
        if manager is None:
            return {"available": False, "reason": "model_manager_unavailable"}
        selected = str(getattr(manager, "current_model", "") or "")
        selected_model = next((item for item in manager._models
                               if str(item.get("id") or "") == selected), {})
        provider = str(selected_model.get("provider") or "")
        provider_config = manager.provider_config(provider) if provider else {}
        provider_key = manager.resolve_api_key(provider) if provider else None
        model_key = (manager.resolve_model_api_key(selected)
                     if selected_model.get("custom") else None)
        custom_endpoint = bool(selected_model.get("custom") and selected_model.get("base_url"))
        gateway_base = str(getattr(manager, "gateway_base_url", "") or "").strip()
        gateway_key = str(getattr(manager, "gateway_api_key", "") or "")
        provider_base = selected_model.get("base_url") or provider_config.get("base_url")
        use_provider_credentials = bool(model_key or provider_key)
        base_url = (provider_base if use_provider_credentials or custom_endpoint
                    else gateway_base or provider_base)
        selection_source = "ModelManager.current_model"
        from atlas.config import get_config, load_user_settings
        if str(load_user_settings().get("selected_model") or "") == selected:
            selection_source = "isolated user_settings.selected_model"
        elif str(get_config().default_model or "") == selected:
            selection_source = "isolated config/atlas.toml models.default"
        from atlas.models.router import _model_for_provider
        wire_model = _model_for_provider(selected_model, native=True) if selected_model else selected
        credential_present = (use_provider_credentials if custom_endpoint or use_provider_credentials
                              else bool(gateway_key))
        from atlas.secrets_store import scrub

        return scrub({
            "available": True,
            "selected_model_id": selected,
            "wire_model": str(wire_model or ""),
            "provider": provider,
            "base_url": str(base_url or ""),
            "source": selection_source,
            "credential_present": credential_present,
            "route_lookup_performed": False,
        })

    server = uvicorn.Server(
        uvicorn.Config(
            app, host="127.0.0.1", port=port, log_level="info",
        )
    )

    async def await_shutdown_request() -> None:
        while not shutdown_file.exists():
            await asyncio.sleep(0.1)
        server.should_exit = True

    serve_task = asyncio.create_task(server.serve())
    shutdown_task = asyncio.create_task(await_shutdown_request())
    try:
        await asyncio.wait(
            (serve_task, shutdown_task), return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        if not shutdown_task.done():
            shutdown_task.cancel()
        await asyncio.gather(shutdown_task, return_exceptions=True)
    await serve_task


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--shutdown-file", required=True, type=Path)
    args = parser.parse_args()
    asyncio.run(_serve(args.port, args.shutdown_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
