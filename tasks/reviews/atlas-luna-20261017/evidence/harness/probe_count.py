
import asyncio, os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from atlas.kernel import model_call

def route():
    return SimpleNamespace(provider="p", wire_model="w", model="w", key="",
                           base_url="http://127.0.0.1", api_mode="chat_completions",
                           model_id="model-a")

def http_error(status, headers=None):
    e = RuntimeError("err"); e.response = SimpleNamespace(status_code=status, headers=headers or {}); return e

async def main():
    calls = {"n": 0}
    def stream(*a, **k):
        calls["n"] += 1
        raise http_error(503)
    router = SimpleNamespace(resolve=AsyncMock(return_value=route()), calls=0, stream=stream)
    agent = SimpleNamespace(_model_router=router)
    err = None
    try:
        await model_call.complete_stream(agent, "model-a", [], [], max_retries=2)
    except Exception as e:
        err = type(e).__name__
    print("PERSISTENT_503 requests=", calls["n"], "exception=", err)

asyncio.run(main())
