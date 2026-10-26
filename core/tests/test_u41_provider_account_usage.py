from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.api.app_services import AppServices
from atlas.models.routes import models_router


class FakeModelManager:
    def __init__(self, base_url: str = "https://api.deepseek.com/v1", key: str | None = "u41-test-key") -> None:
        self.base_url = base_url
        self.key = key

    def provider_config(self, provider_id: str) -> dict[str, Any]:
        return {"base_url": self.base_url, "keys": [{"id": "test-key"}]} if provider_id == "deepseek" else {}

    def resolve_api_key(self, provider_id: str) -> str | None:
        return self.key if provider_id == "deepseek" else None


def make_client(manager: FakeModelManager) -> TestClient:
    app = FastAPI()
    app.state.services = AppServices(model_mgr=manager)
    app.include_router(models_router)
    return TestClient(app)


def test_reads_deepseek_official_balance_without_returning_credential(monkeypatch) -> None:
    import httpx

    calls: list[dict[str, Any]] = []

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"is_available": True, "balance_infos": [
                {"currency": "USD", "total_balance": "12.50", "granted_balance": "2.00", "topped_up_balance": "10.50"},
            ]}

    class AsyncClient:
        def __init__(self, **kwargs: Any) -> None:
            calls.append({"timeout": kwargs["timeout"], "follow_redirects": kwargs["follow_redirects"]})

        async def __aenter__(self) -> "AsyncClient":
            return self

        async def __aexit__(self, *_args: Any) -> None:
            return None

        async def get(self, url: str, *, headers: dict[str, str]) -> Response:
            calls.append({"url": url, "uses_bearer": headers.get("Authorization", "").startswith("Bearer ")})
            return Response()

    monkeypatch.setattr(httpx, "AsyncClient", AsyncClient)
    with make_client(FakeModelManager()) as client:
        response = client.get("/api/providers/account-usage?provider_id=deepseek")
    assert response.status_code == 200
    body = response.json()
    account = body["providers"][0]
    assert account["status"] == "available"
    assert account["balances"][0]["total_balance"] == "12.50"
    assert account["reset_at"] is None
    assert "official-account-api" in body["source"]
    assert "u41-test-key" not in response.text
    assert calls[0] == {"timeout": 8.0, "follow_redirects": False}
    assert calls[1] == {"url": "https://api.deepseek.com/user/balance", "uses_bearer": True}


def test_gateway_and_unconfigured_provider_are_reported_unsupported() -> None:
    with make_client(FakeModelManager("https://gateway.example/v1", "not-used")) as client:
        response = client.get("/api/providers/account-usage?provider_id=deepseek")
    assert response.status_code == 200
    account = response.json()["providers"][0]
    assert account["status"] == "unsupported"
    assert "不是 DeepSeek 官方 API" in account["status_text"]
    assert "not-used" not in response.text


def test_gateway_provider_outside_catalog_is_explicitly_unsupported() -> None:
    # This route iterates configured providers even when the requested id is unknown.
    # Keep this scenario offline so it never probes api.deepseek.com by accident.
    with make_client(FakeModelManager(key=None)) as client:
        response = client.get("/api/providers/account-usage?provider_id=private-gateway")
    assert response.status_code == 200
    account = next(row for row in response.json()["providers"] if row["provider_id"] == "private-gateway")
    assert account["provider_id"] == "private-gateway"
    assert account["status"] == "unsupported"
