"""Write classification for X2 tools (computer / browser).

Imported lazily from ``atlas.engine.atlas_policy`` so ask_writes / auto_file /
plan / read_only gates treat X2 tools like every other state-mutating tool:
unknown defaults to read, and anything that drives the mouse, keyboard,
clipboard, a browser page, or fills vault secrets counts as a write.
"""
from __future__ import annotations

# Pure observers: produce a screenshot / window list / page snapshot / handle
# list, never mutate anything.
X2_READ_TOOLS = frozenset({
    "computer_observe",
    "browser_snapshot",
    "browser_vision",
    "browser_console",
    "browser_vault_list",
    # Not a mutation: it blocks the run and hands control to the human.
    "browser_handoff",
})

# Everything else the X2 surface exposes (computer_window/computer_mouse/
# computer_keyboard/computer_clipboard, browser_navigate/click/type/scroll/
# back/press, browser_vault_fill, browser_replay) injects input or changes
# state and is therefore write-capable.


def is_x2_write_tool(name: str) -> bool:
    if name.startswith("computer_"):
        return name not in X2_READ_TOOLS
    if name.startswith("browser_"):
        return name not in X2_READ_TOOLS
    return False
