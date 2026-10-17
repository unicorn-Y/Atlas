
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from atlas.kernel import model_call

_real = asyncio.sleep
async def _nosleep(*a, **k): return None

def route():
    return SimpleNamespace(provider="p", wire_model="w", model="w", key="",
                           base_url="http://127.0.0.1", api_mode="chat_completions",
                           model_id="model-a")

def http_error(status, headers=None):
    e = RuntimeError("err"); e.response = SimpleNamespace(status_code=status, headers=headers or {}); return e

async def one(status, max_retries, headers=None):
    calls = {"n": 0}
    def stream(*a, **k):
        calls["n"] += 1
        raise http_error(status, headers)
    router = SimpleNamespace(resolve=AsyncMock(return_value=route()), calls=0, stream=stream)
    agent = SimpleNamespace(_model_router=router)
    asyncio.sleep = _nosleep
    try:
        await model_call.complete_stream(agent, "model-a", [], [], max_retries=max_retries)
        return f"status={status} max_retries={max_retries} requests={calls['n']} exc=no-error"
    except Exception as e:
        return f"status={status} max_retries={max_retries} requests={calls['n']} exc={type(e).__name__}"
    finally:
        asyncio.sleep = _real

async def main():
    print("--- no Retry-After header ---")
    for status, mr in ((503, 2), (503, 10), (503, 20), (429, 20), (429, 2)):
        print(await one(status, mr))
    print("--- 429 with Retry-After: 2 ---")
    print(await one(429, 20, {"Retry-After": "2"}))
    print("--- 429 with Retry-After: 60 ---")
    print(await one(429, 20, {"Retry-After": "60"}))

asyncio.run(main())
