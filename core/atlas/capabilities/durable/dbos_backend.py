"""DBOS availability and adapter boundary; durable state remains DBOS-owned."""

from __future__ import annotations

import os
from typing import Any


def status() -> dict[str, Any]:
    try:
        from dbos import DBOS  # noqa: F401
    except ImportError as exc:
        return {"available": False, "status": "missing_dependency", "error": str(exc)}
    database_url = os.environ.get("DBOS_SYSTEM_DATABASE_URL")
    return {
        "available": bool(database_url),
        "status": "ready" if database_url else "misconfigured",
        "error": None if database_url else "DBOS_SYSTEM_DATABASE_URL is not configured",
    }
