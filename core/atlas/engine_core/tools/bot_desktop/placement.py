"""Atlas browser placement policy when the Bot Desktop integration is absent."""

from __future__ import annotations

from dataclasses import dataclass

from . import UNSUPPORTED

GATEWAY = "gateway"
TERMINAL = "terminal"
REFUSED = "refused"


@dataclass(frozen=True)
class Placement:
    where: str
    reason: str = ""


def resolve() -> Placement:
    """Use the Atlas host for the built-in browser; refuse Bot Desktop placement."""
    from atlas.config import get_config

    requested = str(get_config().get("bot_desktop.placement", "gateway") or "gateway").lower()
    if requested in {"gateway", "host"}:
        return Placement(GATEWAY)
    return Placement(REFUSED, f"{UNSUPPORTED} Placement '{requested}' requires Bot Desktop.")
