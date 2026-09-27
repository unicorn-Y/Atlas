"""Native Windows desktop coverage for P18B Computer Use."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from atlas.config import get_config
from atlas.tools.computer_use import COMPUTER_TOOLS, ComputerUseRuntime


def test_computer_use_defaults_to_full_access_and_exposes_native_tools() -> None:
    runtime = ComputerUseRuntime(artifact_dir=Path("data") / "computer-use-tests")

    assert get_config().computer_use_permission_mode == "full_access"
    assert runtime.permission_mode == "full_access"
    assert {item["function"]["name"] for item in COMPUTER_TOOLS} == {
        "computer_observe",
        "computer_window",
        "computer_mouse",
        "computer_keyboard",
        "computer_clipboard",
    }


@pytest.mark.skipif(os.name != "nt", reason="native Computer Use requires Windows")
def test_real_desktop_observe_input_clipboard_and_window_management(tmp_path: Path) -> None:
    import tkinter as tk

    runtime = ComputerUseRuntime(artifact_dir=tmp_path / "observations")
    root = tk.Tk()
    root.title("Atlas P18B isolated Computer Use test")
    root.attributes("-topmost", True)
    root.geometry("420x280+140+140")
    clicked = {"count": 0}
    button = tk.Button(
        root, text="Test click", command=lambda: clicked.update(count=clicked["count"] + 1)
    )
    button.pack()
    text = tk.Text(root, width=45, height=12)
    text.pack()
    root.update()
    hwnd = int(root.wm_frame(), 0)

    try:
        observed = runtime._observe({"target": "desktop"})
        assert not observed["is_error"]
        observation = observed["data"]
        assert observation["coordinate_space"] == "virtual_desktop_physical_pixels"
        assert observation["monitors"]
        assert Path(observation["artifact_path"]).is_file()
        assert observation["image_size"]["width"] > 0
        assert observation["image_size"]["height"] > 0
        assert observation["_image_data_url"].startswith("data:image/png;base64,")

        foreground = runtime._windows()
        assert any(item["window_id"] == hwnd for item in foreground)
        runtime._window({"action": "focus", "window_id": hwnd})
        assert runtime._user32.GetForegroundWindow() in {hwnd, root.winfo_id()}
        text.focus_force()
        root.update()
        runtime._keyboard({"action": "type", "text": "Atlas 中文输入验证"})
        time.sleep(0.05)
        root.update()
        assert "Atlas 中文输入验证" in text.get("1.0", "end-1c")
        runtime._keyboard({"action": "press", "key": "HOME"})
        time.sleep(0.05)
        root.update()
        assert text.index("insert") == "1.0"
        runtime._keyboard({"action": "press", "key": "END"})
        runtime._keyboard({"action": "type", "text": "\nsecond"})
        runtime._keyboard({"action": "press", "key": "END"})
        runtime._keyboard({"action": "hotkey", "keys": ["CTRL", "HOME"]})
        time.sleep(0.05)
        root.update()
        runtime._clipboard({"action": "write", "text": "剪贴板验证"})
        assert runtime._clipboard({"action": "read"})["data"]["text"] == "剪贴板验证"
        runtime._keyboard({"action": "press", "key": "END"})

        root.update()
        bx, by = (
            button.winfo_rootx() + button.winfo_width() // 2,
            button.winfo_rooty() + button.winfo_height() // 2,
        )
        runtime._mouse({"action": "move", "x": bx, "y": by})
        runtime._window({"action": "focus", "window_id": hwnd})
        cursor = runtime._observe({"target": "active_window"})["data"]["cursor"]
        assert abs(cursor["x"] - bx) <= 2 and abs(cursor["y"] - by) <= 2
        mouse_target = runtime._mouse_target(bx, by)
        runtime._mouse({"action": "click", "x": bx, "y": by})
        time.sleep(0.05)
        root.update()
        assert clicked["count"] == 1
        assert runtime._class_name(mouse_target[0]) == "Button"
        runtime._mouse({"action": "double_click", "x": bx, "y": by})
        time.sleep(0.05)
        root.update()
        assert clicked["count"] == 3
        start = (text.winfo_rootx() + 20, text.winfo_rooty() + 20)
        end = (start[0] + 45, start[1] + 10)
        runtime._mouse(
            {"action": "drag", "from_x": start[0], "from_y": start[1], "x": end[0], "y": end[1]}
        )
        runtime._mouse({"action": "scroll", "x": start[0], "y": start[1], "amount": -120})
        runtime._mouse(
            {"action": "scroll", "x": start[0], "y": start[1], "amount": 120, "horizontal": True}
        )

        before = runtime._window_record(hwnd)["bounds"]
        moved = runtime._window(
            {"action": "move", "window_id": hwnd, "x": before["x"] + 30, "y": before["y"] + 20}
        )
        assert moved["data"]["after"]["bounds"]["x"] == before["x"] + 30
        resized = runtime._window(
            {
                "action": "resize",
                "window_id": hwnd,
                "width": before["width"] + 40,
                "height": before["height"] + 30,
            }
        )
        assert resized["data"]["after"]["bounds"]["width"] >= before["width"] + 35
        runtime._window({"action": "minimize", "window_id": hwnd})
        assert runtime._window_record(hwnd)["minimized"]
        runtime._window({"action": "restore", "window_id": hwnd})
        runtime._window({"action": "maximize", "window_id": hwnd})
        assert runtime._window_record(hwnd)["maximized"]
        runtime._window({"action": "restore", "window_id": hwnd})
        runtime._window({"action": "focus", "window_id": hwnd})

        monitors = runtime._observe({"target": "monitor", "monitor_id": 1})["data"]["monitor"]
        assert monitors["width"] > 0 and monitors["height"] > 0
        window_image = runtime._observe({"target": "window", "window_id": hwnd})
        assert window_image["data"]["image_size"]["width"] > 0
        assert runtime._observe({"target": "active_window"})["data"]["image_size"]["height"] > 0
    finally:
        root.destroy()
        asyncio.run(runtime.shutdown())
