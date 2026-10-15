"""Keys for the web_search APIs (Bocha, Tavily).

Keys go to the OS credential store and are never returned from the API; GET
only says whether one is set and where it comes from (credential store or an
environment variable). Changes apply to the next search, no restart needed.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from atlas.tools import search_api
from atlas.tools.web import _describe, system_proxy

router = APIRouter()


class SearchKeyUpdate(BaseModel):
    provider: str
    api_key: str | None = None
    clear: bool = False


class SearchKeyTest(BaseModel):
    provider: str
    query: str = "Atlas AI agent"


def _provider(provider_id: str) -> search_api.SearchProvider:
    provider = search_api.PROVIDERS_BY_ID.get(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"未知的搜索服务：{provider_id}")
    return provider


def _payload() -> dict[str, Any]:
    providers = []
    for provider in search_api.PROVIDERS:
        key, source = search_api.api_key(provider)
        providers.append({
            "id": provider.id, "name": provider.name, "signup_url": provider.signup_url,
            "env_var": provider.env_var, "configured": bool(key), "source": source,
            "hint": f"…{key[-4:]}" if key and len(key) > 8 else None,
        })
    return {
        "providers": providers,
        "order": [provider.id for provider in search_api.PROVIDERS] + ["duckduckgo", "bing"],
    }


@router.get("/api/search-settings")
def get_search_settings() -> dict[str, Any]:
    return _payload()


@router.put("/api/search-settings")
def update_search_settings(req: SearchKeyUpdate) -> dict[str, Any]:
    provider = _provider(req.provider)
    key = (req.api_key or "").strip()
    if req.clear and key:
        raise HTTPException(status_code=422, detail="清除 key 时请勿同时填写新 key。")
    if not req.clear and not key:
        raise HTTPException(status_code=422, detail="请填写 API key。")
    if key and (len(key) > 512 or any(ch.isspace() for ch in key)):
        raise HTTPException(status_code=422, detail="API key 格式不对：不能包含空白字符。")
    store = search_api._credential_store()
    try:
        if req.clear:
            store.delete(provider.credential_key)
        else:
            store.set(provider.credential_key, key)
    except Exception as exc:  # noqa: BLE001 — keys must not fall back to plaintext
        raise HTTPException(status_code=500, detail="无法写入系统凭据库。") from exc
    return _payload()


@router.post("/api/search-settings/test")
async def test_search_settings(req: SearchKeyTest) -> dict[str, Any]:
    provider = _provider(req.provider)
    key, _source = search_api.api_key(provider)
    if not key:
        raise HTTPException(status_code=422, detail=f"{provider.name} 还没有填 key。")
    search = search_api.bocha_search if provider.id == "bocha" else search_api.tavily_search
    started = time.monotonic()
    try:
        results = await search(key, req.query, 3, proxy=system_proxy())
    except Exception as exc:  # noqa: BLE001 — report any failure to the settings page
        return {"ok": False, "error": _describe(exc),
                "seconds": round(time.monotonic() - started, 2)}
    return {
        "ok": True, "count": len(results), "seconds": round(time.monotonic() - started, 2),
        "sample": [{"title": item["title"], "url": item["url"]} for item in results[:3]],
    }
