"""REST surface for the X2 computer runtime (GET /api/computer/status).

The router mirrors the Hermes computer-use doctor output (readiness, driver
version, diagnostics) and never raises: the handler funnels every failure into
an ``{"ok": false, "error": ...}`` payload with a 200 status so the frontend
card can render a degraded state instead of an error page.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter

router = APIRouter(prefix="/api/computer", tags=["computer"])


@router.get("/status")
async def computer_status() -> dict[str, Any]:
    """Desktop-control readiness: Hermes doctor report + Atlas permission state."""
    from atlas.tools.x2.computer import status_snapshot

    return await asyncio.to_thread(status_snapshot)


__all__ = ["router"]
