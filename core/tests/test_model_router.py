from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from atlas.models.router import ModelRouter
from atlas.models.tokens import count_tokens
from tests.fakes.fake_llm_provider import AnthropicReply, FakeLLMServer, Text

PURPOSES = (
    "conversation", "compression", "handoff_summary", "moa", "title", "planning",
    "reflection", "memory_library", "sub_agent", "heartbeat", "group_chat",
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


async def test_complete_for_retries_retryable_failure_on_same_auxiliary_model(monkeypatch) -> None:
    import httpx
    import atlas.models.router as router_module

    router = ModelRouter(FakeModelManager("native_only"))
    route = await router.resolve("claude-sonnet-4", "title")
    resolved: list[str] = []
    original_resolve = router.resolve

    async def record_resolve(model_id, purpose):
        resolved.append(model_id)
        return await original_resolve(model_id, purpose)

    monkeypatch.setattr(router, "resolve", record_resolve)
    attempts = 0

    def post(_route, _messages, _kwargs, _network):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError("temporary connection reset")
        if attempts == 2:
            request = httpx.Request("POST", "https://example.test")
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError("unavailable", request=request, response=response)
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(router_module, "_post_completion", post)
    monkeypatch.setattr(router_module.asyncio, "sleep", lambda _delay: _immediate())

    result = await router.complete_for(route.model_id, "title", [{"role": "user", "content": "x"}], fallbacks=["other"])
    assert result.text == "done"
    assert attempts == 3
    assert resolved == [route.model_id]


async def _immediate() -> None:
    return None


@pytest.mark.parametrize("status", [401, 402, 403, 404, 400])
async def test_complete_for_does_not_retry_permanent_http_failures(monkeypatch, status) -> None:
    import httpx
    import atlas.models.router as router_module

    router = ModelRouter(FakeModelManager("native_only"))
    route = await router.resolve("claude-sonnet-4", "title")
    attempts = 0

    def post(*_args):
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test")
        response = httpx.Response(status, request=request)
        raise httpx.HTTPStatusError("rejected", request=request, response=response)

    monkeypatch.setattr(router_module, "_post_completion", post)
    with pytest.raises(httpx.HTTPStatusError):
        await router.complete_for(route.model_id, "title", [{"role": "user", "content": "x"}])
    assert attempts == 1


async def test_complete_for_stops_on_long_retry_after_and_releases_one_budget_reservation(monkeypatch) -> None:
    import httpx
    import atlas.models.router as router_module

    class Budget:
        cost_limit_usd = None

        def __init__(self):
            self.reserved = 0
            self.released = 0

        def reserve(self, *_args, **_kwargs):
            self.reserved += 1
            return True

        def release(self, _request_id):
            self.released += 1

    budget = Budget()
    monkeypatch.setattr(router_module, "_post_completion", _raise_long_retry_after)
    import atlas.usage
    monkeypatch.setattr(atlas.usage, "env_run_usage_budget", lambda: budget)
    monkeypatch.setattr(router_module.asyncio, "sleep", lambda _delay: _immediate())
    router = ModelRouter(FakeModelManager("native_only"))

    with pytest.raises(httpx.HTTPStatusError):
        await router.complete_for("claude-sonnet-4", "title", [{"role": "user", "content": "x"}])
    assert budget.reserved == 1
    assert budget.released == 1


async def test_complete_for_stops_on_http_date_retry_after_over_15_seconds(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    import httpx
    import atlas.models.router as router_module

    retry_after = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    attempts = 0

    def post(*_args):
        nonlocal attempts
        attempts += 1
        request = httpx.Request("POST", "https://example.test")
        response = httpx.Response(429, headers={"Retry-After": retry_after}, request=request)
        raise httpx.HTTPStatusError("rate limited", request=request, response=response)

    monkeypatch.setattr(router_module, "_post_completion", post)
    router = ModelRouter(FakeModelManager("native_only"))
    with pytest.raises(httpx.HTTPStatusError):
        await router.complete_for("claude-sonnet-4", "title", [{"role": "user", "content": "x"}])
    assert attempts == 1


async def test_complete_for_observes_short_http_date_retry_after(monkeypatch) -> None:
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime
    import httpx
    import atlas.models.router as router_module

    retry_after = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=8), usegmt=True)
    delays: list[float] = []
    attempts = 0

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    def post(*_args):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            request = httpx.Request("POST", "https://example.test")
            response = httpx.Response(429, headers={"Retry-After": retry_after}, request=request)
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return {"choices": [{"message": {"content": "done"}}]}

    monkeypatch.setattr(router_module, "_post_completion", post)
    monkeypatch.setattr(router_module.asyncio, "sleep", record_sleep)
    router = ModelRouter(FakeModelManager("native_only"))
    result = await router.complete_for("claude-sonnet-4", "title", [{"role": "user", "content": "x"}])
    assert result.text == "done"
    assert attempts == 2
    assert len(delays) == 1 and 0 < delays[0] <= 8


def _raise_long_retry_after(*_args):
    import httpx

    request = httpx.Request("POST", "https://example.test")
    response = httpx.Response(429, headers={"Retry-After": "16"}, request=request)
    raise httpx.HTTPStatusError("rate limited", request=request, response=response)


async def test_native_anthropic_route_preserves_cache_thinking_signature_and_tool_blocks(
) -> None:
    """Round 1 returns a signed thinking block + tool_use; round 2 replays both verbatim.

    Messages use the OpenAI-internal shape the aux transport documents: signed
    thinking rides the ``reasoning_details`` carrier, tools pair via
    ``tool_calls`` + ``role: "tool"``, and caller-placed ``cache_control``
    breakpoints survive conversion. The fake endpoint is a third-party host, so
    the thinking policy is pinned to ``native`` exactly like a direct Anthropic
    route.
    """
    manager = FakeModelManager("native_only")
    round_one_messages = [
        {"role": "system", "content": "You are Atlas."},
        # breakpoint rides inside content, the shape apply_anthropic_cache_control produces
        {"role": "user", "content": [
            {"type": "text", "text": "Lookup the thing.", "cache_control": {"type": "ephemeral"}},
        ]},
    ]
    round_one_reply = AnthropicReply(blocks=[
        {"type": "thinking", "thinking": "need the lookup tool", "signature": "sig_round1"},
        {"type": "tool_use", "id": "tool_1", "name": "lookup", "input": {"q": "x"}},
    ])
    with FakeLLMServer(
        [round_one_reply], default_text="native reply", api_key="sk-native-secret", anthropic_messages=True,
    ) as server:
        provider_base = server.base_url.replace("/v1", "/anthropic/v1")
        manager.provider_config = lambda _provider: {  # type: ignore[method-assign]
            "base_url": provider_base, "keys": [{"id": "native-key-1"}],
        }
        router = ModelRouter(manager)
        route = await router.resolve("claude-sonnet-4", "conversation")
        assert route.api_mode == "anthropic_messages"

        first = await router.complete(route, round_one_messages, max_tokens=64)
        first_record = next(r for r in server.requests if r["kind"] == "anthropic")
        first_wire = first_record["body"]
        assert first_record["path"].endswith("/anthropic/v1/messages")
        assert first_record["auth"] == "sk-native-secret"
        # provider-reported usage is surfaced for token accounting
        assert count_tokens(round_one_messages, usage=first.usage) == 16

        tool_call = first.raw.choices[0].message.tool_calls[0]
        round_two_messages = [
            *round_one_messages,
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "id": tool_call.id, "type": "function",
                    "function": {"name": tool_call.name, "arguments": tool_call.arguments},
                }],
                "reasoning_details": [
                    {"type": "thinking", "thinking": "need the lookup tool", "signature": "sig_round1"},
                ],
            },
            {"role": "tool", "tool_call_id": tool_call.id, "content": "found"},
        ]
        await router.complete(route, round_two_messages, max_tokens=64)
        second_wire = next(
            r["body"] for r in reversed(server.requests) if r["kind"] == "anthropic"
        )

        # stable prefix: the cached prefix is byte-identical across rounds
        # (the converter hoists the system message out of ``messages``)
        assert second_wire["messages"][0] == first_wire["messages"][0]
        assert second_wire.get("system") == first_wire.get("system")
        # signed thinking block replayed verbatim
        assistant = second_wire["messages"][1]
        thinking = [b for b in assistant["content"] if b.get("type") == "thinking"]
        assert thinking == [{"type": "thinking", "thinking": "need the lookup tool", "signature": "sig_round1"}]
        # tool_use / tool_result pairing survives conversion
        tool_use = next(b for b in assistant["content"] if b.get("type") == "tool_use")
        assert tool_use["id"] == tool_call.id and tool_use["name"] == "lookup"
        final_message = second_wire["messages"][2]
        tool_results = [b for b in final_message["content"] if b.get("type") == "tool_result"]
        assert [b["tool_use_id"] for b in tool_results] == [tool_call.id]
        assert tool_results[0]["content"] == "found"
        # a cache_control breakpoint is present on the wire
        assert _wire_cache_control_count(second_wire) >= 1


def _wire_cache_control_count(wire: dict) -> int:
    def _walk(node: object) -> int:
        if isinstance(node, dict):
            total = 1 if "cache_control" in node else 0
            return total + sum(_walk(value) for value in node.values())
        if isinstance(node, list):
            return sum(_walk(item) for item in node)
        return 0

    return _walk(wire.get("messages")) + _walk(wire.get("system") or {})


async def test_gateway_probe_uses_real_http_and_caches_result() -> None:
    """/v1/messages probing runs against the actual gateway and is cached per credential."""
    for supports, expected_mode in ((True, "anthropic_messages"), (False, "chat_completions")):
        with FakeLLMServer(default_text="ok", api_key="sk-gateway-secret", anthropic_messages=supports) as server:
            manager = FakeModelManager("gateway_only")
            manager.gateway_base_url = server.base_url
            manager.gateway_api_key = "sk-gateway-secret"
            router = ModelRouter(manager)
            route = await router.resolve("claude-sonnet-4", "title")

            assert route.api_mode == expected_mode
            assert route.base_url == server.base_url
            assert route.key == "sk-gateway-secret"
            if supports:
                assert route.fallback_reason is None
            else:
                assert "404" in (route.fallback_reason or "")
            probe_count = len(server.anthropic_requests())
            assert probe_count >= 1
            again = await router.resolve("claude-sonnet-4", "compression")
            assert again.api_mode == expected_mode
            assert len(server.anthropic_requests()) == probe_count  # probe result cached


class _RelayModelManager:
    """Host-shaped custom relay model: prefixed litellm id, no explicit native id.

    This is exactly the H10.2 live-smoke configuration: a ChatCompletions
    relay that 404s the litellm-prefixed wire id (H10.2-DEFECT-1).
    """

    def __init__(self, *, native_model: str | None = None) -> None:
        entry = {
            "id": "deepseek-v4.1-flash", "provider": "openai", "hermes_provider": "openai",
            "litellm_model": "openai/deepseek-v4.1-flash",
        }
        if native_model is not None:
            entry["native_model"] = native_model
        self.models = [entry]
        self.gateway_base_url = ""
        self.gateway_api_key = ""

    def list_models(self):
        return list(self.models)

    def provider_config(self, _provider_id: str) -> dict:
        return {}

    def resolve_api_key(self, _provider_id: str):
        return None

    def credential_pool(self, _provider_id: str):
        return None

    def get_api_mode_override(self, _provider_id: str):
        return None

    def get_api_mode_probe(self, _provider_id: str):
        return None

    def set_api_mode_probe(self, _provider_id: str, _probe: dict) -> None:
        pass


async def _relay_route(native_model: str | None = None):
    manager = _RelayModelManager(native_model=native_model)
    manager.gateway_base_url = "https://relay.example/v1"
    manager.gateway_api_key = "sk-relay-secret"
    return await ModelRouter(manager).resolve("deepseek-v4.1-flash", "conversation")


async def test_chat_completions_route_keeps_registry_id_but_exposes_bare_wire_model() -> None:
    """H10.2-DEFECT-1: the litellm routing prefix must never reach the wire."""
    route = await _relay_route()

    assert route.api_mode == "chat_completions"
    # The registry's litellm-style id stays on the spec for litellm-style consumers.
    assert route.model == "openai/deepseek-v4.1-flash"
    # The wire model is the bare id the relay actually exposes.
    assert route.wire_model == "deepseek-v4.1-flash"


async def test_hermes_agent_kwargs_carry_the_wire_model_not_the_litellm_prefix() -> None:
    """The pinned AIAgent must receive the bare wire id on chat_completions routes."""
    kwargs = ModelRouter.hermes_agent_kwargs(await _relay_route())

    assert kwargs["model"] == "deepseek-v4.1-flash"
    assert kwargs["api_mode"] == "chat_completions"


async def test_explicit_native_model_wins_for_the_wire_id() -> None:
    route = await _relay_route(native_model="deepseek-chat-wire-alias")

    assert route.wire_model == "deepseek-chat-wire-alias"
    assert ModelRouter.hermes_agent_kwargs(route)["model"] == "deepseek-chat-wire-alias"


async def test_auxiliary_complete_sends_bare_wire_model_over_http() -> None:
    """``complete()`` rides the same raw wire as the agent: bare id, no prefix."""
    route = await _relay_route()
    assert route.wire_model == "deepseek-v4.1-flash"

    # The gateway fallback route points at the relay; point it at the fake instead.
    from dataclasses import replace

    with FakeLLMServer(aux=lambda _req: Text("relay reply"), api_key="sk-relay-secret") as server:
        route = replace(route, base_url=server.base_url, key="sk-relay-secret")
        result = await ModelRouter(_RelayModelManager()).complete(
            route, [{"role": "user", "content": "hello"}],
        )

        assert result.text == "relay reply"
        requests = server.aux_requests()
        assert len(requests) == 1
        assert requests[0]["model"] == "deepseek-v4.1-flash"
        assert server.requests[0]["auth"] == "Bearer sk-relay-secret"


def test_ast_no_acompletion_outside_router() -> None:
    """AST gate: no direct litellm calls outside ``atlas.models.router``.

    All lanes have wired their call sites through ``atlas.models.router``
    (agent MoA summary / trajectory review / plan / verify / goal evaluation
    included, H2); files still listed here are other lanes' wiring tickets.
    The set may only shrink. ``atlas/models/`` must already be clean, and the
    router itself goes through Hermes' transport instead of litellm.
    """
    pending_unification: set[str] = set()
    core_dir = Path(__file__).resolve().parents[1] / "atlas"
    repo_root = core_dir.parents[1]
    offenders: dict[str, list[str]] = {}
    for path in sorted(core_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = _litellm_hits(tree)
        if hits:
            offenders[path.relative_to(repo_root).as_posix()] = hits

    models_dir = core_dir / "models"
    models_hits = {file: hits for file, hits in offenders.items()
                   if (core_dir / file).is_relative_to(models_dir)}
    assert models_hits == {}, f"litellm direct calls inside atlas/models: {models_hits}"
    unexpected = sorted(set(offenders) - pending_unification)
    assert unexpected == [], (
        "new litellm direct call sites must go through atlas.models.router, got: "
        f"{unexpected}; shrink pending_unification as lanes wire up"
    )


def _litellm_hits(tree: ast.AST) -> list[str]:
    """Report litellm completion entry points (imports and direct calls).

    Metadata probes are not completion calls: ``get_supported_openai_params``
    (capability introspection, kept per the H4/H5 spec) and friends import
    litellm without ever sending a model request, so they are not hits.
    """
    completion_call_names = {
        "acompletion", "completion", "batch_completion", "text_completion",
    }
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "litellm" or alias.name.startswith("litellm."):
                    hits.append(f"import litellm (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom) and node.module == "litellm":
            names = [alias.name for alias in node.names if alias.name in completion_call_names]
            if names:
                hits.append(f"from litellm import {', '.join(names)} (line {node.lineno})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "acompletion":
            hits.append(f"acompletion call (line {node.lineno})")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "acompletion":
            hits.append(f"acompletion call (line {node.lineno})")
    return hits
