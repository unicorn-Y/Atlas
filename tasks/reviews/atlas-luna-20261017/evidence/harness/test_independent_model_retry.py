"""
Independent verification suite for Atlas Model Retry Policy (W1 Patch).
Uses a real local HTTP server (fake gateway) that handles real HTTP requests
over localhost sockets, testing real complete_stream() calls with direct ModelRouter.stream transport.
"""

import asyncio
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import Any, List, Optional
from unittest.mock import AsyncMock

import pytest

from atlas.kernel import model_call
from atlas.kernel.model_call import ModelCallError, complete_stream
from atlas.models.router import ModelRouter, RouteSpec


class FakeGatewayHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        pass  # quiet

    def do_POST(self) -> None:
        server: "FakeGatewayServer" = self.server  # type: ignore
        content_len = int(self.headers.get("Content-Length", 0) or 0)
        raw_body = self.rfile.read(content_len) if content_len > 0 else b""
        try:
            body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception:
            body = {}

        req_record = {
            "path": self.path,
            "headers": dict(self.headers),
            "body": body,
            "model": body.get("model"),
            "time": time.time(),
        }
        with server.lock:
            server.recorded_requests.append(req_record)
            idx = len(server.recorded_requests) - 1
            if idx < len(server.script):
                behavior = server.script[idx]
            else:
                behavior = server.default_behavior

        # Dispatch behavior
        b_type = behavior.get("type", "success")
        if b_type == "connection_drop":
            # abrupt disconnect
            self.close_connection = True
            return

        if b_type == "error":
            status = behavior.get("status", 500)
            err_body = json.dumps(behavior.get("body", {"error": {"message": f"HTTP {status}"}})).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(err_body)))
            for k, v in behavior.get("headers", {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(err_body)
            return

        if b_type == "stream_text":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            chunks = behavior.get("chunks", ["Hello", " world!"])
            for c in chunks:
                chunk_obj = {
                    "choices": [{"delta": {"content": c}, "finish_reason": None}]
                }
                self.wfile.write(f"data: {json.dumps(chunk_obj)}\n\n".encode("utf-8"))
                self.wfile.flush()

            stop_chunk = {
                "choices": [{"delta": {}, "finish_reason": "stop"}]
            }
            self.wfile.write(f"data: {json.dumps(stop_chunk)}\n\ndata: [DONE]\n\n".encode("utf-8"))
            self.wfile.flush()
            return

        if b_type == "partial_stream_then_disconnect":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            chunks = behavior.get("chunks", ["First partial text"])
            for c in chunks:
                chunk_obj = {
                    "choices": [{"delta": {"content": c}, "finish_reason": None}]
                }
                self.wfile.write(f"data: {json.dumps(chunk_obj)}\n\n".encode("utf-8"))
                self.wfile.flush()

            # Abruptly drop connection without [DONE] or finish_reason
            # Reset connection cleanly so client gets connection error or stream end
            self.close_connection = True
            return

        if b_type == "partial_tool_then_disconnect":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.end_headers()

            tool_chunk = {
                "choices": [{
                    "delta": {
                        "tool_calls": [{
                            "index": 0,
                            "id": "call_123",
                            "function": {"name": "execute_tool", "arguments": '{"param": "val"'}
                        }]
                    },
                    "finish_reason": None
                }]
            }
            self.wfile.write(f"data: {json.dumps(tool_chunk)}\n\n".encode("utf-8"))
            self.wfile.flush()

            self.close_connection = True
            return

        # default success
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Connection", "close")
        self.end_headers()
        ok_chunk = {
            "choices": [{"delta": {"content": "OK"}, "finish_reason": "stop"}]
        }
        self.wfile.write(f"data: {json.dumps(ok_chunk)}\n\ndata: [DONE]\n\n".encode("utf-8"))
        self.wfile.flush()


class FakeGatewayServer(ThreadingHTTPServer):
    def __init__(self, host: str, port: int, script: List[dict]):
        super().__init__((host, port), FakeGatewayHandler)
        self.script = script
        self.default_behavior = {"type": "stream_text", "chunks": ["fallback OK"]}
        self.recorded_requests: List[dict] = []
        self.lock = threading.Lock()


class GatewayContext:
    def __init__(self, script: List[dict]):
        self.script = script
        self.server: Optional[FakeGatewayServer] = None
        self.thread: Optional[threading.Thread] = None
        self.port: int = 0

    def __enter__(self):
        # find free port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = FakeGatewayServer("127.0.0.1", self.port, self.script)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def requests(self) -> List[dict]:
        assert self.server is not None
        with self.server.lock:
            return list(self.server.recorded_requests)


def make_agent(base_url: str, wire_model: str = "gpt-4o", model_id: str = "model-a"):
    route = RouteSpec(
        provider="test-provider",
        api_mode="openai",
        model=model_id,
        wire_model=wire_model,
        model_id=model_id,
        base_url=base_url,
        key="fake-test-key",
        network_proxy_url=None,
        network_ca_bundle_path=None,
    )
    router = ModelRouter(model_manager=None)
    router.resolve = AsyncMock(return_value=route)
    agent = SimpleNamespace(_model_router=router)
    return agent, route


# -------------------------------------------------------------
# Test 1: 网络瞬断一次（第一次连接异常/503），同模型第二次成功
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec1_transient_failure_retries_and_succeeds(monkeypatch):
    """规格 1: 第一次 503，第二次成功 -> 最终成功，请求总数=2，没有换模型。"""
    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())

    script = [
        {"type": "error", "status": 503, "body": {"error": {"message": "Service Temporarily Unavailable"}}},
        {"type": "stream_text", "chunks": ["Hello ", "world"]},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="primary-wire-model", model_id="primary-model")
        result = await complete_stream(agent, "primary-model", [{"role": "user", "content": "hi"}], [])

        assert result.text == "Hello world"
        assert result.attempts == 2
        assert len(gw.requests) == 2
        assert gw.requests[0]["model"] == "primary-wire-model"
        assert gw.requests[1]["model"] == "primary-wire-model"


# -------------------------------------------------------------
# Test 2: 持续 503 -> 最多 3 次 HTTP 请求，抛出包含字段的 ModelCallError
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec2_continuous_503_caps_at_3_and_records_fields(monkeypatch):
    """规格 2: 持续 503 -> 同一模型总共最多 3 次 HTTP 请求（首次+2次重试），抛错且字段完整。"""
    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())

    script = [
        {"type": "error", "status": 503, "body": {"error": {"message": "503 Unavailable 1"}}},
        {"type": "error", "status": 503, "body": {"error": {"message": "503 Unavailable 2"}}},
        {"type": "error", "status": 503, "body": {"error": {"message": "503 Unavailable 3"}}},
        {"type": "error", "status": 503, "body": {"error": {"message": "503 Unavailable 4"}}},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec2-wire", model_id="spec2-model")
        with pytest.raises(ModelCallError) as exc_info:
            await complete_stream(agent, "spec2-model", [{"role": "user", "content": "hi"}], [], max_retries=10)

        err = exc_info.value
        assert len(gw.requests) == 3  # exactly 3 attempts
        for req in gw.requests:
            assert req["model"] == "spec2-wire"
        assert err.attempts == 3
        assert err.status == 503
        assert err.category in {"provider", "connection", "overloaded"}
        assert err.model == "spec2-model"
        assert err.provider == "test-provider"


# -------------------------------------------------------------
# Test 3: 401 / 402 / 404 -> 只请求 1 次，不重试，直接抛错
# -------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 402, 404])
async def test_spec3_permanent_errors_fail_immediately_no_retry(monkeypatch, status_code):
    """规格 3: 401 / 402 / 404 -> 只请求 1 次，不重试，直接抛错。"""
    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())

    script = [
        {"type": "error", "status": status_code, "body": {"error": {"message": f"Client permanent error {status_code}"}}},
        {"type": "stream_text", "chunks": ["Should never reach"]},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec3-wire", model_id="spec3-model")
        with pytest.raises(ModelCallError) as exc_info:
            await complete_stream(agent, "spec3-model", [{"role": "user", "content": "hi"}], [], max_retries=2)

        err = exc_info.value
        assert len(gw.requests) == 1
        assert err.attempts == 1
        assert err.status == status_code


# -------------------------------------------------------------
# Test 4: 模型 A 失败时绝不打到模型 B；complete_for 不追加 deepseek
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec4_no_fallback_model_request_and_complete_for_clean():
    """规格 4: 指定模型 A 失败时，全程没有任何请求打到模型 B；complete_for 不隐式追加 deepseek。"""
    # 验证 complete_stream 不切模型
    script = [
        {"type": "error", "status": 503, "body": {"error": {"message": "Model A broken"}}},
        {"type": "error", "status": 503, "body": {"error": {"message": "Model A broken"}}},
        {"type": "error", "status": 503, "body": {"error": {"message": "Model A broken"}}},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="model-A-wire", model_id="model-A")
        with pytest.raises(ModelCallError):
            await complete_stream(
                agent,
                "model-A",
                [{"role": "user", "content": "hi"}],
                [],
                fallback_models=["model-B", "deepseek-v4.1-flash"],
                max_retries=2
            )
        assert len(gw.requests) == 3
        for req in gw.requests:
            assert req["model"] == "model-A-wire"
            assert req["model"] != "model-B"
            assert "deepseek" not in req["model"]

    # 验证 complete_for 不追加 deepseek
    router = ModelRouter(model_manager=None)
    resolved_models = []

    async def mock_resolve(model_id, purpose):
        resolved_models.append(model_id)
        raise RuntimeError(f"Cannot resolve {model_id}")

    router.resolve = mock_resolve
    with pytest.raises(RuntimeError):
        await router.complete_for("model-A", "memory", [], fallbacks=["model-B", "model-C"])

    assert resolved_models == ["model-A"]
    assert "deepseek-v4.1-flash" not in resolved_models
    assert "deepseek-v3" not in resolved_models


# -------------------------------------------------------------
# Test 5: 429 带 Retry-After 行为 (2s 重试, 60s 立即抛错且记录字段)
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec5_retry_after_threshold_behavior(monkeypatch):
    """规格 5: 429 带 Retry-After: 2 (<15s) 会重试；带 Retry-After: 60 (>15s) 不重试立即抛错且记录 retry_after_s。"""
    wait_mock = AsyncMock()
    monkeypatch.setattr(model_call, "_wait_for_retry", wait_mock)

    # 5.1 Retry-After: 2 -> 重试成功
    script_short = [
        {"type": "error", "status": 429, "headers": {"Retry-After": "2", "x-request-id": "req-429-short"}, "body": {"error": {"message": "Rate limited"}}},
        {"type": "stream_text", "chunks": ["OK after rate limit"]},
    ]
    with GatewayContext(script_short) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec5-wire", model_id="spec5-model")
        result = await complete_stream(agent, "spec5-model", [{"role": "user", "content": "hi"}], [], max_retries=2)
        assert result.text == "OK after rate limit"
        assert result.attempts == 2
        assert len(gw.requests) == 2
        assert wait_mock.await_count == 1
        assert wait_mock.call_args[0][0] == 2.0  # delay is 2.0

    wait_mock.reset_mock()

    # 5.2 Retry-After: 60 -> 超过 15s，立即放弃不重试
    script_long = [
        {"type": "error", "status": 429, "headers": {"Retry-After": "60", "x-request-id": "req-429-long"}, "body": {"error": {"message": "Rate limited for 60s"}}},
        {"type": "stream_text", "chunks": ["Should not be called"]},
    ]
    with GatewayContext(script_long) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec5-wire", model_id="spec5-model")
        with pytest.raises(ModelCallError) as exc_info:
            await complete_stream(agent, "spec5-model", [{"role": "user", "content": "hi"}], [], max_retries=2)

        err = exc_info.value
        assert len(gw.requests) == 1
        assert err.attempts == 1
        assert err.status == 429
        assert err.retry_after_s == 60
        # request_id can either be from x-request-id header or uuid generated fallback
        assert err.request_id == "req-429-long" or (err.request_id and len(err.request_id) == 32)
        assert wait_mock.await_count == 0  # no wait!


# -------------------------------------------------------------
# Test 6: 流式已产出部分 text delta 后连接中断 -> 不重发该请求
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec6_partial_text_stream_drop_not_retried(monkeypatch):
    """规格 6: 流式已产出部分 text delta 后连接中断 -> 不重发该请求（请求总数=1）。"""
    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())

    script = [
        {"type": "partial_stream_then_disconnect", "chunks": ["Hello partially emitted"]},
        {"type": "stream_text", "chunks": ["Duplicate run text"]},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec6-wire", model_id="spec6-model")
        received_chunks = []
        with pytest.raises(ModelCallError) as exc_info:
            await complete_stream(
                agent,
                "spec6-model",
                [{"role": "user", "content": "hi"}],
                [],
                max_retries=2,
                on_text=received_chunks.append
            )

        err = exc_info.value
        assert len(gw.requests) == 1  # Not reissued!
        assert err.attempts == 1
        assert "".join(received_chunks) == "Hello partially emitted"


# -------------------------------------------------------------
# Test 7: 工具调用 delta 已产生后失败 -> 不重发
# -------------------------------------------------------------
@pytest.mark.asyncio
async def test_spec7_partial_tool_delta_drop_not_retried(monkeypatch):
    """规格 7: 若工具调用 delta 已产生后失败 -> 不重发（避免工具副作用重放）。"""
    monkeypatch.setattr(model_call, "_wait_for_retry", AsyncMock())

    script = [
        {"type": "partial_tool_then_disconnect"},
        {"type": "stream_text", "chunks": ["Duplicate run text"]},
    ]

    with GatewayContext(script) as gw:
        agent, route = make_agent(gw.base_url, wire_model="spec7-wire", model_id="spec7-model")
        received_events = []
        with pytest.raises(ModelCallError) as exc_info:
            await complete_stream(
                agent,
                "spec7-model",
                [{"role": "user", "content": "hi"}],
                [],
                max_retries=2,
                on_event=received_events.append
            )

        err = exc_info.value
        assert len(gw.requests) == 1  # Not reissued!
        assert err.attempts == 1
        # tool delta was delivered to on_event
        tool_deltas = [ev for ev in received_events if ev.get("type") == "tool_call_delta"]
        assert len(tool_deltas) > 0
        assert tool_deltas[0]["name"] == "execute_tool"
