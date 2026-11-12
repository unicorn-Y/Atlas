"""Loopback proxy bypass helpers used by the local browser process."""
from __future__ import annotations

import os
from urllib.parse import urlsplit


def add_loopback_no_proxy(env: dict[str, str]) -> dict[str, str]:
    result = dict(env)
    for key in ("NO_PROXY", "no_proxy"):
        existing = [part for part in result.get(key, "").split(",") if part]
        result[key] = ",".join(dict.fromkeys([*existing, "localhost", "127.0.0.1", "::1"]))
    return result


def loopback_connect_kwargs(host: str | None = None) -> dict:
    return {"trust_env": False} if host in {"localhost", "127.0.0.1", "::1"} else {}


def loopback_request_kwargs(url: str) -> dict:
    try:
        return loopback_connect_kwargs(urlsplit(url).hostname)
    except ValueError:
        return {}

