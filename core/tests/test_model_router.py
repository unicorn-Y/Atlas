from __future__ import annotations

from dataclasses import dataclass

import pytest

from atlas.models.router import ModelRouter
from tests.fakes.fake_llm_provider import FakeLLMServer


PURPOSES = (
    "conversation", "compression", "handoff_summary", "moa", "title", "planning",
    "reflection", "goal_knowledge", "sub_agent", "heartbeat", "group_chat",
    "skill_workshop", "safety_review", "model_test",
)


@dataclass
class FakeCredentialEntry:
    runtime_api_key: str = "sk-native-secret"


@dataclass
class FakeCredentialPool:
    marker: str = "native-pool"

    def select(self, *, model: str):
        return FakeCredentialEntry()


class FakeModelManager:
    def __init__(self, mode: str) -> None:
        self.models = [{
            "id": "claude-sonnet-4", "provider": "anthropic", "hermes_provider": "anthropic",
            "litellm_model": "anthropic/claude-sonnet-4", "native_model": "claude-sonnet-4",
        }]
        self.gateway_base_url = "https://gateway.example/v1" if mode != "native_only" else ""
        self.gateway_api_key = "sk-gateway-secret" if mode != "native_only" else ""
        self._native_key = "sk-native-secret" if mode != "gateway_only" else ""
        self.mode = mode
        self.probes: list[dict[str, str]] = []
        self.probe_cache: dict[str, dict] = {}
        self.override: str | None = None
        self.pool = FakeCredentialPool() if self._native_key else None

    def list_models(self):
        return self.models

    def provider_config(self, provider_id: str) -> dict:
        if self._native_key:
            return {"base_url": "https://api.anthropic.com", "keys": [{"id": "native-key-1"}]}
        return {}

    def resolve_api_key(self, provider_id: str):
        return self._native_key or None

    def credential_pool(self, provider_id: str):
        return self.pool

    def get_api_mode_override(self, provider_id: str):
        return self.override

    def get_api_mode_probe(self, provider_id: str):
        return self.probe_cache.get(provider_id)

    def set_api_mode_probe(self, provider_id: str, value: dict) -> None:
        self.probe_cache[provider_id] = value


@pytest.mark.parametrize("purpose", PURPOSES)
@pytest.mark.parametrize("mode", ("gateway_only", "native_only", "both"))
async def test_all_purposes_resolve_for_gateway_and_native_credentials(mode, purpose) -> None:
    manager = FakeModelManager(mode)

    async def probe(base_url: str, api_key: str, model: str):
        manager.probes.append({"base_url": base_url, "model": model})
        return True, None

    router = ModelRouter(manager, native_probe=probe)
    route = await router.resolve("claude-sonnet-4", purpose)

    assert route.provider == "anthropic"
    assert route.api_mode == "anthropic_messages"
    assert route.model == "claude-sonnet-4"
    assert route.purpose == purpose
    if mode == "gateway_only":
        assert route.base_url == manager.gateway_base_url
        assert route.key == "sk-gateway-secret"
        assert manager.probes == [{
            "base_url": manager.gateway_base_url,
            "model": "claude-sonnet-4",
        }]
    else:
        assert route.base_url == "https://api.anthropic.com"
        assert route.key == "sk-native-secret"
        assert route.credential_pool is manager.pool
        assert manager.probes == []


async def test_gateway_probe_fallback_reason_is_cached_and_key_is_not_repr() -> None:
    manager = FakeModelManager("gateway_only")
    manager.gateway_base_url = "https://gateway.example/v1/"
    calls = 0

    async def probe(base_url: str, api_key: str, model: str):
        nonlocal calls
        calls += 1
        return False, "gateway returned 404 for /v1/messages"

    router = ModelRouter(manager, native_probe=probe)
    first = await router.resolve("claude-sonnet-4", "title")
    second = await router.resolve("claude-sonnet-4", "compression")

    assert first.api_mode == second.api_mode == "chat_completions"
    assert first.fallback_reason == "gateway returned 404 for /v1/messages"
    assert calls == 1
    assert "sk-gateway-secret" not in repr(first)


async def test_manual_override_takes_precedence_over_probe() -> None:
    manager = FakeModelManager("gateway_only")
    manager.override = "chat_completions"
    calls = 0

    async def probe(*_args):
        nonlocal calls
        calls += 1
        return True, None

    route = await ModelRouter(manager, native_probe=probe).resolve("claude-sonnet-4", "moa")

    assert route.api_mode == "chat_completions"
    assert route.fallback_reason is None
    assert calls == 0


@pytest.mark.parametrize("purpose", PURPOSES)
async def test_native_anthropic_route_completes_over_fake_http_endpoint(purpose) -> None:
    manager = FakeModelManager("native_only")
    with FakeLLMServer(default_text="native reply", api_key="sk-native-secret", anthropic_messages=True) as server:
        manager.provider_config = lambda _provider: {  # type: ignore[method-assign]
            "base_url": server.base_url.replace("/v1", "/anthropic/v1"),
            "keys": [{"id": "native-key-1"}],
        }
        router = ModelRouter(manager)
        route = await router.resolve("claude-sonnet-4", purpose)
        result = await router.complete(route, [{"role": "user", "content": "hello"}], max_tokens=12)

        assert result.text == "native reply"
        assert len(server.anthropic_requests()) == 1
        request = server.requests[0]
        assert request["auth"] == "sk-native-secret"
        assert request["path"].endswith("/anthropic/v1/messages")
        assert request["body"]["model"] == "claude-sonnet-4"


async def test_native_anthropic_route_preserves_cache_thinking_signature_and_tool_blocks() -> None:
    manager = FakeModelManager("native_only")
    content = [
        {"type": "text", "text": "cached prefix", "cache_control": {"type": "ephemeral"}},
        {"type": "thinking", "thinking": "reasoning", "signature": "sig_fake"},
        {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"q": "x"}},
    ]
    messages = [
        {"role": "assistant", "content": content},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tool_1", "content": "found"}]},
    ]
    with FakeLLMServer(default_text="native reply", api_key="sk-native-secret", anthropic_messages=True) as server:
        manager.provider_config = lambda _provider: {
            "base_url": server.base_url.replace("/v1", "/anthropic/v1"), "keys": [{"id": "native-key-1"}],
        }
        router = ModelRouter(manager)
        route = await router.resolve("claude-sonnet-4", "conversation")
        await router.complete(route, messages, max_tokens=12)

        sent = server.anthropic_requests()[0]
        assert sent["messages"] == messages
