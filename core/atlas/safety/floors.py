"""Operations no reviewer may approve: Hermes' hardline set plus Atlas' Windows floors."""

from __future__ import annotations

from atlas.safety.detection import assess


def floor_reason(command: str) -> str | None:
    found = assess("local_shell", {"command": command or ""}, workspace=None)
    return f"这条操作触及不可恢复的底线：{found.floor}。" if found.floor else None
