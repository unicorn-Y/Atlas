"""Explicitly unavailable Lightpanda backend for the Atlas-owned engine.

The built-in Atlas browser uses local agent-browser/Chromium. Lightpanda is not
installed or launched by Atlas; callers receive an explicit unsupported result
if a Hermes profile selects that backend.
"""

from __future__ import annotations

from dataclasses import dataclass


UNSUPPORTED = "The Lightpanda browser backend is not supported by Atlas. Select the built-in Chromium backend."


@dataclass
class LightpandaServer:
    cdp_url: str = ""
    port: int = 0

    def is_alive(self) -> bool:
        return False


def launch_lightpanda(session_name: str, *, block_private_networks: bool = False):
    del session_name, block_private_networks
    return None, UNSUPPORTED


def get_server(session_name: str):
    del session_name
    return None


def stop_lightpanda(session_name: str) -> None:
    del session_name


def stop_all_lightpanda() -> None:
    return None


def reap_orphaned_lightpanda() -> int:
    return 0
