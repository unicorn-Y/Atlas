"""Small pywinauto semantic UI adapter; no custom UIA framework."""

from __future__ import annotations

from typing import Any


def list_windows() -> list[dict[str, Any]]:
    from pywinauto import Desktop

    return [
        {"title": window.window_text(), "handle": window.handle, "class_name": window.class_name()}
        for window in Desktop(backend="uia").windows()
        if window.is_visible() and window.window_text()
    ]
