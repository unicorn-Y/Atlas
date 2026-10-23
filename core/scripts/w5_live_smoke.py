"""W5 live-model smoke for configured Atlas routing and tool-call history.

The credential store is loaded by Atlas from ATLAS_ROOT. This script never
reads, prints, or copies credential values.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any


MODEL_ID = "deepseek-v4.1-flash"


def _manager() -> Any:
    from atlas.models import ModelManager

    class ReadOnlyModelManager(ModelManager):
        def set_api_mode_probe(self, provider_id: str, probe: dict[str, Any]) -> None:
            return None

        def credential_pool(self, provider_id: str) -> None:
            return None

    return ReadOnlyModelManager()


async def _run(model_override: str | None) -> None:
    root_value = os.environ.get("ATLAS_ROOT")
    if not root_value:
        raise RuntimeError("ATLAS_ROOT is required")
    if not Path(root_value).expanduser().resolve().is_dir():
        raise RuntimeError("ATLAS_ROOT does not exist")

    model = model_override or MODEL_ID
    manager = _manager()
    config = next((item for item in manager.list_models()
                   if item.get("id") == model or item.get("litellm_model") == model), None)
    gateway = str(getattr(manager, "gateway_base_url", "") or "").lower()
    if model != MODEL_ID or config is None or "d1api" not in gateway:
        raise RuntimeError("W5 smoke requires the configured d1api deepseek-v4.1-flash route")
    agent = SimpleNamespace(_model_router=manager.model_router, source="foreground")

    from atlas.kernel.model_call import complete_stream

    plain = await complete_stream(
        agent, model,
        [{"role": "user", "content": "Reply with exactly W5-LIVE-TEXT-OK"}],
        [], max_output_tokens=48, max_retries=1,
    )
    if "W5-LIVE-TEXT-OK" not in (plain.text or ""):
        raise RuntimeError("real model text response did not contain the requested marker")
    print("real model text response: PASS", flush=True)

    tools = [{
        "type": "function",
        "function": {
            "name": "w5_live_echo",
            "description": "Return the supplied marker to the W5 live smoke.",
            "parameters": {
                "type": "object", "properties": {"value": {"type": "string"}},
                "required": ["value"], "additionalProperties": False,
            },
        },
    }]
    tool_turn = await complete_stream(
        agent, model,
        [{"role": "user", "content": (
            "Call the w5_live_echo function exactly once with value W5-LIVE-TOOL-OK. "
            "Do not answer in ordinary text."
        )}],
        tools, max_output_tokens=96, max_retries=1,
    )
    call = next((item for item in tool_turn.tool_calls if item.get("name") == "w5_live_echo"), None)
    if call is None or call.get("arg_error") or not isinstance(call.get("args"), dict):
        raise RuntimeError("real model did not return a valid w5_live_echo tool call")
    call_id = str(call.get("id") or "")
    if not call_id:
        raise RuntimeError("real model tool call had no call id")
    print("real model tool-call response: PASS", flush=True)

    continuation = await complete_stream(
        agent, model,
        [
            {"role": "user", "content": (
                "Call the w5_live_echo function exactly once with value W5-LIVE-TOOL-OK. "
                "Do not answer in ordinary text."
            )},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": call_id, "type": "function", "function": {
                    "name": "w5_live_echo", "arguments": json.dumps(call["args"]),
                },
            }]},
            {"role": "tool", "tool_call_id": call_id,
             "name": "w5_live_echo", "content": "W5-LIVE-TOOL-OK"},
        ],
        tools, max_output_tokens=48, max_retries=1,
    )
    if "W5-LIVE-TOOL-OK" not in (continuation.text or ""):
        raise RuntimeError("real model did not consume the tool result in its continuation")
    print("real model tool-result continuation: PASS", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", help="override configured model (must be deepseek-v4.1-flash)")
    args = parser.parse_args()
    try:
        asyncio.run(_run(args.model))
    except BaseException as exc:
        reason = " ".join(str(exc).split())
        reason = re.sub(r"(?i)\bsk-[A-Za-z0-9_-]+", "[REDACTED]", reason)
        reason = re.sub(r"(?i)(api[_-]?key|access[_-]?token|authorization|bearer)\s*[:=]\s*[^\s,;]+",
                        r"\1=[REDACTED]", reason)
        print(f"FAIL: {type(exc).__name__}: {reason[:500]}", flush=True)
        return 1
    print("W5 LIVE SMOKE PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
