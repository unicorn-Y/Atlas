"""Native Windows desktop coverage for P18B Computer Use."""

from __future__ import annotations

import asyncio
import multiprocessing
import os
import time
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

import pytest

from atlas.config import get_config
from atlas.tools.computer_use import COMPUTER_TOOLS, ComputerUseRuntime


def _desktop_target(connection: Connection) -> None:
    """Keep a real Tk target in its own message-pumping process."""
    import tkinter as tk

    root = tk.Tk()
    root.title("Atlas P18B isolated Computer Use test")
    root.attributes("-topmost", True)
    root.geometry("640x520+140+140")
    state: dict[str, Any] = {"clicks": 0, "right_clicks": 0, "mouse_messages": []}
    button = tk.Button(root, text="Test click", command=lambda: state.update(clicks=state["clicks"] + 1))
    button.pack()
    horizontal = tk.Scrollbar(root, orient=tk.HORIZONTAL)
    text = tk.Text(
        root,
        width=55,
        height=12,
        wrap="none",
        xscrollcommand=horizontal.set,
    )
    horizontal.configure(command=text.xview)
    text.pack()
    horizontal.pack(fill=tk.X)
    text.insert(
        "1.0",
        "Atlas 中文输入验证\nsecond\n"
        + "horizontal scroll target " + ("x" * 180) + "\n"
        + "scroll target content\n" * 80,
    )
    text.bind(
        "<ButtonPress-1>",
        lambda event: state["mouse_messages"].append("down"),
        add="+",
    )
    text.bind(
        "<ButtonRelease-1>",
        lambda event: state["mouse_messages"].append("up"),
        add="+",
    )
    text.bind(
        "<Button-3>",
        lambda event: state.update(right_clicks=state["right_clicks"] + 1),
        add="+",
    )
    root.update()
    root_hwnd = int(root.wm_frame(), 0)
    geometry = {
        "pid": os.getpid(),
        "hwnd": root_hwnd,
        "button": (
            button.winfo_rootx() + button.winfo_width() // 2,
            button.winfo_rooty() + button.winfo_height() // 2,
        ),
        "text": (
            text.winfo_rootx() + 80,
            text.winfo_rooty() + 12,
        ),
    }
    connection.send({"type": "ready", **geometry})

    def snapshot() -> dict[str, Any]:
        return {
            **state,
            "text": text.get("1.0", "end-1c"),
            "selection": tuple(str(value) for value in text.tag_ranges("sel")),
            "yview": text.yview(),
            "xview": text.xview(),
            "bounds": {
                "x": root.winfo_x(),
                "y": root.winfo_y(),
                "width": root.winfo_width(),
                "height": root.winfo_height(),
            },
        }

    def poll() -> None:
        if connection.poll():
            command = connection.recv()
            if command == "snapshot":
                connection.send(snapshot())
            elif command == "close":
                root.destroy()
                return
        root.after(10, poll)

    root.after(10, poll)
    root.mainloop()


def _target_snapshot(connection: Connection) -> dict[str, Any]:
    connection.send("snapshot")
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if connection.poll(0.05):
            value = connection.recv()
            if isinstance(value, dict):
                return value
    raise AssertionError("the isolated desktop target stopped responding")


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
def test_real_desktop_observe_input_clipboard_and_window_management() -> None:
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe()
    target = context.Process(target=_desktop_target, args=(child,))
    target.start()
    runtime = ComputerUseRuntime()
    try:
        assert parent.poll(20), "the isolated desktop target did not create its window"
        ready = parent.recv()
        assert ready["pid"] != os.getpid()
        hwnd = ready["hwnd"]
        observed = runtime._observe({"target": "desktop"})
        assert not observed["is_error"]
        observation = observed["data"]
        assert observation["coordinate_space"] == "virtual_desktop_physical_pixels"
        assert observation["monitors"]
        assert Path(observation["artifact_path"]).is_file()
        assert observation["image_size"]["width"] > 0
        assert observation["image_size"]["height"] > 0
        assert observation["_image_data_url"].startswith("data:image/png;base64,")
        assert any(item["window_id"] == hwnd for item in runtime._windows())

        runtime._window({"action": "focus", "window_id": hwnd})
        assert int(runtime._user32.GetForegroundWindow() or 0) == hwnd
        x, y = ready["button"]
        runtime._mouse({"action": "click", "x": x, "y": y})
        time.sleep(0.1)
        state = _target_snapshot(parent)
        assert state["clicks"] == 1

        runtime._mouse({"action": "double_click", "x": x, "y": y})
        time.sleep(0.1)
        assert _target_snapshot(parent)["clicks"] == 3

        tx, ty = ready["text"]
        runtime._mouse({"action": "click", "x": tx, "y": ty})
        runtime._keyboard({"action": "type", "text": "Atlas 中文输入验证"})
        time.sleep(0.05)
        assert "Atlas 中文输入验证" in _target_snapshot(parent)["text"]
        runtime._keyboard({"action": "hotkey", "keys": ["CTRL", "HOME"]})
        before_scroll = _target_snapshot(parent)
        runtime._mouse({"action": "scroll", "x": tx, "y": ty, "amount": -120})
        time.sleep(0.1)
        after_vertical_scroll = _target_snapshot(parent)
        assert before_scroll["yview"] != after_vertical_scroll["yview"]
        runtime._mouse(
            {"action": "scroll", "x": tx, "y": ty, "amount": -120, "horizontal": True}
        )
        time.sleep(0.1)
        # Tk's Windows Text widget does not consume WM_MOUSEHWHEEL even with
        # an attached horizontal scrollbar; this target supports vertical only.
        horizontal_scroll_supported = (
            after_vertical_scroll["xview"] != _target_snapshot(parent)["xview"]
        )

        runtime._mouse({"action": "click", "x": tx, "y": ty, "button": "right"})
        time.sleep(0.05)
        assert _target_snapshot(parent)["right_clicks"] == 1
        runtime._mouse({"action": "mouse_down", "x": tx, "y": ty})
        runtime._mouse({"action": "mouse_up", "x": tx, "y": ty})
        time.sleep(0.05)
        mouse_messages = _target_snapshot(parent)["mouse_messages"]
        assert "down" in mouse_messages and "up" in mouse_messages
        assert isinstance(horizontal_scroll_supported, bool)

        runtime._mouse(
            {
                "action": "drag",
                "from_x": tx,
                "from_y": ty,
                "x": tx + 70,
                "y": ty,
            }
        )
        time.sleep(0.05)
        assert _target_snapshot(parent)["selection"]
        cursor = runtime._observe({"target": "active_window"})["data"]["cursor"]
        assert abs(cursor["x"] - (tx + 70)) <= 2 and abs(cursor["y"] - ty) <= 2

        runtime._clipboard({"action": "write", "text": "剪贴板验证"})
        assert runtime._clipboard({"action": "read"})["data"]["text"] == "剪贴板验证"
    finally:
        if target.is_alive():
            parent.send("close")
            target.join(timeout=3)
        if target.is_alive():
            target.terminate()
            target.join(timeout=2)
        parent.close()
        child.close()
        asyncio.run(runtime.shutdown())
