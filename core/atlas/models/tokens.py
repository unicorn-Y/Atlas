"""Provider usage first, model-aware token estimates otherwise."""

from __future__ import annotations

import json
import threading
from typing import Any

import structlog

log = structlog.get_logger()


def _usage_input_tokens(usage: Any) -> int | None:
    if usage is None:
        return None
    for name in ("input_tokens", "prompt_tokens"):
        value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None


# tiktoken downloads a BPE file (~1.7 MB, from openaipublic.blob.core.windows.net) the
# first time an encoding is used. That used to happen synchronously inside the first
# plan/compaction on the event loop and could stall the backend for as long as the
# download took (forever offline). Encodings now load on a background thread; until one
# is ready, estimates use Atlas's CJK-aware estimator.
_ENCODINGS: dict[str, Any] = {}
_UNAVAILABLE: set[str] = set()
_LOADING: set[str] = set()
_LOCK = threading.Lock()


def _encoding_name(model: str) -> str:
    try:
        from tiktoken.model import encoding_name_for_model

        return encoding_name_for_model(model) if model else "cl100k_base"
    except (ImportError, KeyError):
        return "cl100k_base"


def _load_encoding(name: str) -> None:
    try:
        import tiktoken

        encoding = tiktoken.get_encoding(name)
    except Exception:  # noqa: BLE001 — download/IO/format errors all mean "use the fallback"
        log.debug("tokens.tiktoken_load_failed", encoding=name, exc_info=True)
        with _LOCK:
            _UNAVAILABLE.add(name)
            _LOADING.discard(name)
        return
    with _LOCK:
        _ENCODINGS[name] = encoding
        _LOADING.discard(name)


def _ready_encoding(name: str) -> Any | None:
    """The encoding if already loaded; otherwise start loading it and return None."""
    with _LOCK:
        if name in _ENCODINGS:
            return _ENCODINGS[name]
        if name in _UNAVAILABLE or name in _LOADING:
            return None
        _LOADING.add(name)
    threading.Thread(target=_load_encoding, args=(name,), name=f"tiktoken-{name}",
                     daemon=True).start()
    return None


def prefetch(model: str = "") -> None:
    """Load the encoding on the calling thread (use from a worker thread at startup)."""
    name = _encoding_name(model)
    with _LOCK:
        if name in _ENCODINGS or name in _UNAVAILABLE:
            return
        _LOADING.add(name)
    _load_encoding(name)


def estimate_tokens(
    value: str | list[dict[str, Any]] | dict[str, Any],
    *,
    model: str = "",
    system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Estimate tokens with tiktoken once loaded; use the CJK-aware estimator until then."""
    encoding = _ready_encoding(_encoding_name(model))
    if encoding is not None:
        if isinstance(value, str):
            material = value
        else:
            material = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if system_prompt:
            material = system_prompt + "\n" + material
        if tools:
            material += "\n" + json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
        return len(encoding.encode(material))

    from atlas.engine_core.agent.model_metadata import estimate_request_tokens_rough

    if isinstance(value, str):
        messages = [{"role": "user", "content": value}]
    elif isinstance(value, dict):
        messages = [value]
    else:
        messages = value
    return estimate_request_tokens_rough(messages, system_prompt=system_prompt, tools=tools)


def count_tokens(
    value: str | list[dict[str, Any]] | dict[str, Any],
    *,
    model: str = "",
    usage: Any = None,
    system_prompt: str = "",
    tools: list[dict[str, Any]] | None = None,
) -> int:
    """Return provider-reported input usage when present, otherwise an actual tokenizer estimate."""
    reported = _usage_input_tokens(usage)
    if reported is not None:
        return reported
    return estimate_tokens(value, model=model, system_prompt=system_prompt, tools=tools)
