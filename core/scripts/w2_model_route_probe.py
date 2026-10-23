"""Probe per-custom-model key routing and gateway isolation."""
import asyncio
from types import SimpleNamespace

from atlas.models.router import ModelRouter


class Manager:
    gateway_base_url = "https://gateway.invalid/v1"
    gateway_api_key = "gateway-sentinel"

    def __init__(self, model_key=None, api_mode=None):
        self.model_key = model_key
        self.api_mode = api_mode

    def list_models(self):
        return [{"id": "my-custom", "custom": True, "provider": "openai",
                 "hermes_provider": "openai", "litellm_model": "openai/example",
                 "base_url": "https://custom.invalid/v1", "api_mode": self.api_mode}]

    def provider_config(self, _provider):
        return {}

    def resolve_api_key(self, _provider):
        return None

    def resolve_model_api_key(self, _model):
        return self.model_key

    def credential_pool(self, _provider):
        return None

    def get_api_mode_override(self, _provider):
        return None


async def main():
    route = await ModelRouter(Manager()).resolve("my-custom", "chat")
    assert route.base_url == "https://custom.invalid/v1" and route.key is None
    route = await ModelRouter(Manager("model-sentinel")).resolve("my-custom", "chat")
    assert route.base_url == "https://custom.invalid/v1" and route.key == "model-sentinel"
    route = await ModelRouter(Manager("model-sentinel", "anthropic_messages")).resolve("my-custom", "chat")
    from atlas.models.router import _request_details
    _url, headers, _payload = _request_details(route, [], {})
    assert route.api_mode == "anthropic_messages" and headers["x-api-key"] == "model-sentinel"
    print("W2-7 custom endpoint key isolation and model-specific credentials: PASS")


if __name__ == "__main__":
    asyncio.run(main())
