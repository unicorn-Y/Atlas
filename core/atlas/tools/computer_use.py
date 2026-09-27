"""Windows desktop observation and input tools for the existing Atlas Agent loop."""

from __future__ import annotations

import asyncio
import base64
import ctypes
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import mss
import mss.tools

from atlas.config import get_config


def _tool(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


COMPUTER_TOOLS = [
    _tool(
        "computer_observe",
        (
            "Capture the real Windows desktop or a monitor/window and return the image to your "
            "next visual reasoning step. Coordinates use virtual desktop pixels, including "
            "negative monitor origins."
        ),
        {
            "target": {"type": "string", "enum": ["desktop", "monitor", "active_window", "window"]},
            "monitor_id": {"type": "integer", "minimum": 1},
            "window_id": {"type": "integer", "minimum": 1},
        },
        [],
    ),
    _tool(
        "computer_window",
        (
            "List and manage ordinary visible Windows application windows. Window ids are HWND "
            "values returned by list/observe."
        ),
        {
            "action": {
                "type": "string",
                "enum": [
                    "list",
                    "focus",
                    "restore",
                    "minimize",
                    "maximize",
                    "move",
                    "resize",
                    "close",
                ],
            },
            "window_id": {"type": "integer", "minimum": 1},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "width": {"type": "integer", "minimum": 1},
            "height": {"type": "integer", "minimum": 1},
        },
        ["action"],
    ),
    _tool(
        "computer_mouse",
        "Control the real Windows mouse in virtual desktop screenshot coordinates.",
        {
            "action": {
                "type": "string",
                "enum": [
                    "move",
                    "move_relative",
                    "click",
                    "double_click",
                    "mouse_down",
                    "mouse_up",
                    "drag",
                    "scroll",
                ],
            },
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "dx": {"type": "integer"},
            "dy": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "amount": {"type": "integer"},
            "horizontal": {"type": "boolean"},
            "from_x": {"type": "integer"},
            "from_y": {"type": "integer"},
        },
        ["action"],
    ),
    _tool(
        "computer_keyboard",
        (
            "Type Unicode text or send Windows keys/hotkeys. Unicode text uses native SendInput "
            "and supports Chinese."
        ),
        {
            "action": {"type": "string", "enum": ["type", "press", "down", "up", "hotkey"]},
            "text": {"type": "string"},
            "key": {"type": "string"},
            "keys": {"type": "array", "items": {"type": "string"}},
        },
        ["action"],
    ),
    _tool(
        "computer_clipboard",
        "Read or write the current Windows user's text clipboard.",
        {"action": {"type": "string", "enum": ["read", "write"]}, "text": {"type": "string"}},
        ["action"],
    ),
]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", _RECT),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


_KEYS = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "CONTROL": 0x11,
    "ALT": 0x12,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESC": 0x1B,
    "ESCAPE": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "WIN": 0x5B,
    "LWIN": 0x5B,
    "RWIN": 0x5C,
}
_KEYS.update({f"F{i}": 0x6F + i for i in range(1, 25)})
_KEYS.update({str(i): ord(str(i)) for i in range(10)})
_KEYS.update({chr(i): i for i in range(ord("A"), ord("Z") + 1)})


class ComputerUseRuntime:
    """Native Windows computer-use runtime. All actions are FULL_ACCESS by default."""

    def __init__(self, artifact_dir: Path | None = None) -> None:
        self.permission_mode = get_config().computer_use_permission_mode
        self.artifact_dir = (
            artifact_dir
            or Path(os.environ.get("ATLAS_DATA_DIR", Path.cwd() / "data")) / "computer-use"
        )
        self._artifacts: list[Path] = []
        self._closed = False
        self._user32: Any = None
        self._kernel32: Any = None
        if os.name == "nt":
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._user32.GetForegroundWindow.restype = ctypes.c_void_p
            self._user32.EnumWindows.restype = ctypes.c_bool
            hwnd = ctypes.c_void_p
            self._user32.IsWindow.argtypes = [hwnd]
            self._user32.IsWindowVisible.argtypes = [hwnd]
            self._user32.IsIconic.argtypes = [hwnd]
            self._user32.IsZoomed.argtypes = [hwnd]
            self._user32.GetWindowTextLengthW.argtypes = [hwnd]
            self._user32.GetWindowTextW.argtypes = [hwnd, ctypes.c_wchar_p, ctypes.c_int]
            self._user32.GetWindowRect.argtypes = [hwnd, ctypes.POINTER(_RECT)]
            self._user32.GetWindowThreadProcessId.argtypes = [hwnd, ctypes.POINTER(ctypes.c_ulong)]
            self._user32.ShowWindow.argtypes = [hwnd, ctypes.c_int]
            self._user32.SetForegroundWindow.argtypes = [hwnd]
            self._user32.BringWindowToTop.argtypes = [hwnd]
            self._user32.SetActiveWindow.argtypes = [hwnd]
            self._user32.SetWindowPos.argtypes = [
                hwnd,
                hwnd,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_uint,
            ]
            self._user32.AttachThreadInput.argtypes = [
                ctypes.c_ulong,
                ctypes.c_ulong,
                ctypes.c_bool,
            ]
            self._user32.MoveWindow.argtypes = [
                hwnd,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_bool,
            ]
            self._user32.PostMessageW.argtypes = [
                hwnd,
                ctypes.c_uint,
                ctypes.c_size_t,
                ctypes.c_ssize_t,
            ]
            self._user32.SendMessageW.argtypes = self._user32.PostMessageW.argtypes
            self._user32.SendMessageW.restype = ctypes.c_ssize_t
            self._user32.GetGUIThreadInfo.argtypes = [
                ctypes.c_ulong,
                ctypes.POINTER(_GUITHREADINFO),
            ]
            self._user32.GetGUIThreadInfo.restype = ctypes.c_bool
            self._user32.WindowFromPoint.argtypes = [_POINT]
            self._user32.WindowFromPoint.restype = hwnd
            self._user32.GetClassNameW.argtypes = [hwnd, ctypes.c_wchar_p, ctypes.c_int]
            self._user32.GetAncestor.argtypes = [hwnd, ctypes.c_uint]
            self._user32.GetAncestor.restype = hwnd
            self._user32.ScreenToClient.argtypes = [hwnd, ctypes.POINTER(_POINT)]
            self._user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
            self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
            self._user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
            self._user32.EnumWindows.argtypes = [
                ctypes.WINFUNCTYPE(ctypes.c_bool, hwnd, ctypes.c_void_p),
                ctypes.c_void_p,
            ]
            self._user32.OpenClipboard.argtypes = [hwnd]
            self._user32.GetClipboardData.restype = ctypes.c_void_p
            self._user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
            self._kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
            self._kernel32.OpenProcess.restype = ctypes.c_void_p
            self._kernel32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p,
                ctypes.c_ulong,
                ctypes.c_wchar_p,
                ctypes.POINTER(ctypes.c_ulong),
            ]
            self._kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
            self._kernel32.GlobalAlloc.restype = ctypes.c_void_p
            self._kernel32.GlobalLock.restype = ctypes.c_void_p
            self._kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            self._kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            self._kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
            self._kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            self._kernel32.GetCurrentThreadId.restype = ctypes.c_ulong
            try:
                ctypes.WinDLL("shcore", use_last_error=True).SetProcessDpiAwareness(2)
            except (AttributeError, OSError):
                try:
                    self._user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
                except (AttributeError, OSError):
                    pass

    def get_tools_for_llm(self) -> list[dict[str, Any]]:
        return COMPUTER_TOOLS

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.permission_mode != "full_access":
            return self._error(
                f"Computer Use is disabled by permission_mode={self.permission_mode!r}."
            )
        if os.name != "nt" or self._user32 is None:
            return self._error("Computer Use requires the active Windows desktop session.")
        if self._closed:
            return self._error("Computer Use runtime is shutting down.")
        args = arguments or {}
        try:
            if name == "computer_observe":
                return await asyncio.to_thread(self._observe, args)
            if name == "computer_window":
                return await asyncio.to_thread(self._window, args)
            if name == "computer_mouse":
                return await asyncio.to_thread(self._mouse, args)
            if name == "computer_keyboard":
                return await asyncio.to_thread(self._keyboard, args)
            if name == "computer_clipboard":
                return await asyncio.to_thread(self._clipboard, args)
            return self._error(f"Unknown Computer Use tool: {name}")
        except Exception as exc:
            return self._error(f"{name} failed: {exc}")

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {
            "data": {"error": message},
            "content": [{"type": "text", "text": message}],
            "is_error": True,
        }

    def _windows(self) -> list[dict[str, Any]]:
        windows: list[dict[str, Any]] = []
        callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def visit(hwnd: int, _param: int) -> bool:
            if not self._user32.IsWindowVisible(hwnd):
                return True
            title_len = self._user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(max(title_len + 1, 2))
            self._user32.GetWindowTextW(hwnd, title_buf, len(title_buf))
            rect = _RECT()
            if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return True
            pid = ctypes.c_ulong()
            self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process_name = ""
            handle = self._kernel32.OpenProcess(0x1000, False, pid.value)
            if handle:
                try:
                    image_buf = ctypes.create_unicode_buffer(32768)
                    size = ctypes.c_ulong(len(image_buf))
                    if self._kernel32.QueryFullProcessImageNameW(
                        handle, 0, image_buf, ctypes.byref(size)
                    ):
                        process_name = Path(image_buf.value).name
                finally:
                    self._kernel32.CloseHandle(handle)
            bounds = {
                "x": rect.left,
                "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            }
            if bounds["width"] > 0 and bounds["height"] > 0:
                windows.append(
                    {
                        "window_id": int(hwnd),
                        "title": title_buf.value,
                        "process_name": process_name,
                        "pid": pid.value,
                        "bounds": bounds,
                        "visible": True,
                        "minimized": bool(self._user32.IsIconic(hwnd)),
                        "maximized": bool(self._user32.IsZoomed(hwnd)),
                    }
                )
            return True

        if not self._user32.EnumWindows(callback_type(visit), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        return windows

    def _observe(self, args: dict[str, Any]) -> dict[str, Any]:
        target = args.get("target", "desktop")
        with mss.MSS() as capture:
            monitors = [dict(m) for m in capture.monitors[1:]]
            if not monitors:
                raise RuntimeError("Windows reported no screenshot-capable monitors")
            if target == "desktop":
                monitor = dict(capture.monitors[0])
            elif target == "monitor":
                index = int(args.get("monitor_id", 1))
                if index < 1 or index >= len(capture.monitors):
                    raise ValueError(
                        f"monitor_id must be between 1 and {len(capture.monitors) - 1}"
                    )
                monitor = dict(capture.monitors[index])
            else:
                hwnd_value = (
                    args["window_id"] if target == "window" else self._user32.GetForegroundWindow()
                )
                hwnd = int(hwnd_value or 0)
                if not hwnd or not self._user32.IsWindow(hwnd):
                    raise ValueError("No valid target window is available")
                rect = _RECT()
                if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    raise ctypes.WinError(ctypes.get_last_error())
                monitor = {
                    "left": rect.left,
                    "top": rect.top,
                    "width": rect.right - rect.left,
                    "height": rect.bottom - rect.top,
                }
                if monitor["width"] <= 0 or monitor["height"] <= 0:
                    raise ValueError("Target window has no drawable bounds")
            shot = capture.grab(monitor)
            png = mss.tools.to_png(shot.rgb, shot.size)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        image_id = str(uuid.uuid4())
        image_path = self.artifact_dir / f"{image_id}.png"
        image_path.write_bytes(png)
        self._artifacts.append(image_path)
        self._cleanup_artifacts()
        cursor = _POINT()
        if not self._user32.GetCursorPos(ctypes.byref(cursor)):
            raise ctypes.WinError(ctypes.get_last_error())
        foreground = int(self._user32.GetForegroundWindow() or 0)
        observation = {
            "observation_id": image_id,
            "target": target,
            "monitor": monitor,
            "monitors": monitors,
            "coordinate_space": "virtual_desktop_physical_pixels",
            "cursor": {"x": cursor.x, "y": cursor.y},
            "foreground_window_id": foreground,
            "windows": self._windows(),
            "artifact_path": str(image_path),
            "image_size": {"width": shot.width, "height": shot.height},
        }
        data_url = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        return {
            "data": {**observation, "_image_data_url": data_url},
            "content": [{"type": "text", "text": json.dumps(observation, ensure_ascii=False)}],
            "is_error": False,
        }

    def _cleanup_artifacts(self) -> None:
        while len(self._artifacts) > 8:
            old = self._artifacts.pop(0)
            old.unlink(missing_ok=True)

    def _window(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args["action"]
        if action == "list":
            windows = self._windows()
            foreground = int(self._user32.GetForegroundWindow() or 0)
            return self._success(
                {"action": action, "foreground_window_id": foreground, "windows": windows}
            )
        hwnd = int(args["window_id"])
        if not self._user32.IsWindow(hwnd):
            raise ValueError(f"Unknown window_id {hwnd}")
        before = self._window_record(hwnd)
        show = {"restore": 9, "minimize": 6, "maximize": 3}
        if action in show:
            self._user32.ShowWindow(hwnd, show[action])
        elif action == "focus":
            self._focus_window(hwnd)
        elif action in {"move", "resize"}:
            rect = before["bounds"]
            x = int(args.get("x", rect["x"]))
            y = int(args.get("y", rect["y"]))
            width = int(args.get("width", rect["width"])) if action == "resize" else rect["width"]
            height = (
                int(args.get("height", rect["height"])) if action == "resize" else rect["height"]
            )
            if not self._user32.MoveWindow(hwnd, x, y, width, height, True):
                raise ctypes.WinError(ctypes.get_last_error())
        elif action == "close":
            if not self._user32.PostMessageW(hwnd, 0x0010, 0, 0):
                raise ctypes.WinError(ctypes.get_last_error())
        else:
            raise ValueError(f"Unsupported window action: {action}")
        time.sleep(0.08)
        after = self._window_record(hwnd) if self._user32.IsWindow(hwnd) else None
        return self._success(
            {
                "action": action,
                "window_id": hwnd,
                "before": before,
                "after": after,
                "foreground_window_id": int(self._user32.GetForegroundWindow() or 0),
            }
        )

    def _focus_window(self, hwnd: int) -> None:
        self._user32.ShowWindow(hwnd, 9)
        foreground = self._user32.GetForegroundWindow()
        if foreground == hwnd:
            return
        foreground_thread = (
            self._user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
        )
        current_thread = self._kernel32.GetCurrentThreadId()
        attached = bool(
            foreground_thread
            and self._user32.AttachThreadInput(current_thread, foreground_thread, True)
        )
        try:
            self._user32.BringWindowToTop(hwnd)
            self._user32.SetForegroundWindow(hwnd)
            self._user32.SetActiveWindow(hwnd)
            if self._user32.GetForegroundWindow() != hwnd:
                self._send_key(0x12, 0)
                self._send_key(0x12, 0x0002)
                self._user32.SetForegroundWindow(hwnd)
            if self._user32.GetForegroundWindow() != hwnd:
                self._user32.SetWindowPos(
                    hwnd, ctypes.c_void_p(0), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040
                )
                self._user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                self._user32.AttachThreadInput(current_thread, foreground_thread, False)
        if self._user32.GetForegroundWindow() != hwnd:
            raise RuntimeError(f"Windows denied focus activation for window {hwnd}")

    def _window_record(self, hwnd: int) -> dict[str, Any]:
        rect = _RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        title = ctypes.create_unicode_buffer(max(self._user32.GetWindowTextLengthW(hwnd) + 1, 2))
        self._user32.GetWindowTextW(hwnd, title, len(title))
        pid = ctypes.c_ulong()
        self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return {
            "window_id": hwnd,
            "title": title.value,
            "pid": pid.value,
            "bounds": {
                "x": rect.left,
                "y": rect.top,
                "width": rect.right - rect.left,
                "height": rect.bottom - rect.top,
            },
            "visible": bool(self._user32.IsWindowVisible(hwnd)),
            "minimized": bool(self._user32.IsIconic(hwnd)),
            "maximized": bool(self._user32.IsZoomed(hwnd)),
        }

    def _mouse(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args["action"]
        pos = _POINT()
        self._user32.GetCursorPos(ctypes.byref(pos))
        x, y = int(args.get("x", pos.x)), int(args.get("y", pos.y))
        if action == "move_relative":
            x, y = pos.x + int(args.get("dx", 0)), pos.y + int(args.get("dy", 0))
            self._move_mouse(x, y)
        elif action == "move":
            self._move_mouse(x, y)
        elif action in {"click", "double_click", "mouse_down", "mouse_up", "drag"}:
            button = args.get("button", "left")
            flags = {
                "left": (0x0002, 0x0004),
                "right": (0x0008, 0x0010),
                "middle": (0x0020, 0x0040),
            }
            if button not in flags:
                raise ValueError(f"Unsupported mouse button: {button}")
            down, up = flags[button]
            self._move_mouse(x, y)
            if action == "mouse_down":
                self._send_mouse(down)
            elif action == "mouse_up":
                self._send_mouse(up)
            elif action == "click":
                self._send_mouse(down)
                self._send_mouse(up)
            elif action == "double_click":
                for _ in range(2):
                    self._send_mouse(down)
                    self._send_mouse(up)
                    time.sleep(0.05)
            else:
                start_x, start_y = int(args.get("from_x", pos.x)), int(args.get("from_y", pos.y))
                self._move_mouse(start_x, start_y)
                self._send_mouse(down)
                self._move_mouse(x, y)
                self._send_mouse(up)
        elif action == "scroll":
            amount = int(args.get("amount", 0))
            if not amount:
                raise ValueError("scroll amount must be nonzero")
            self._move_mouse(x, y)
            horizontal = bool(args.get("horizontal", False))
            self._send_mouse(0x1000 if horizontal else 0x0800, mouse_data=amount)
        else:
            raise ValueError(f"Unsupported mouse action: {action}")
        final = _POINT()
        self._user32.GetCursorPos(ctypes.byref(final))
        return self._success(
            {
                "action": action,
                "coordinates": {"x": final.x, "y": final.y},
                "foreground_window_id": int(self._user32.GetForegroundWindow() or 0),
            }
        )

    def _move_mouse(self, x: int, y: int) -> None:
        vx, vy = self._user32.GetSystemMetrics(76), self._user32.GetSystemMetrics(77)
        vw, vh = self._user32.GetSystemMetrics(78), self._user32.GetSystemMetrics(79)
        if vw <= 1 or vh <= 1 or not (vx <= x < vx + vw and vy <= y < vy + vh):
            raise ValueError(
                f"Coordinates ({x}, {y}) are outside virtual desktop bounds "
                f"({vx}, {vy}, {vw}, {vh})"
            )
        ax = round((x - vx) * 65535 / (vw - 1))
        ay = round((y - vy) * 65535 / (vh - 1))
        self._send_mouse(0x0001 | 0x4000 | 0x8000, ax, ay)

    def _send_mouse(self, flags: int, x: int = 0, y: int = 0, mouse_data: int = 0) -> None:
        self._send_mouse_events([(flags, x, y, mouse_data)])

    def _send_mouse_events(
        self, events: list[tuple[int, int, int] | tuple[int, int, int, int]]
    ) -> None:
        inputs_list = []
        for event in events:
            flags, x, y = event[:3]
            mouse_data = event[3] if len(event) == 4 else 0
            inputs_list.append(_INPUT(type=0, mi=_MOUSEINPUT(x, y, mouse_data, flags, 0, None)))
        inputs = (_INPUT * len(inputs_list))(*inputs_list)
        if self._user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT)) != len(inputs):
            raise ctypes.WinError(ctypes.get_last_error())

    def _mouse_target(self, x: int, y: int) -> tuple[int, int, int]:
        hwnd = int(self._user32.WindowFromPoint(_POINT(x, y)) or 0)
        if not hwnd:
            raise RuntimeError(f"No window is under mouse coordinates ({x}, {y})")
        point = _POINT(x, y)
        if not self._user32.ScreenToClient(hwnd, ctypes.byref(point)):
            raise ctypes.WinError(ctypes.get_last_error())
        return hwnd, point.x, point.y

    def _class_name(self, hwnd: int) -> str:
        buffer = ctypes.create_unicode_buffer(256)
        self._user32.GetClassNameW(hwnd, buffer, len(buffer))
        return buffer.value

    @staticmethod
    def _packed_point(x: int, y: int) -> int:
        return (x & 0xFFFF) | ((y & 0xFFFF) << 16)

    def _post_mouse_button(self, x: int, y: int, button: str, state: str) -> None:
        hwnd, cx, cy = self._mouse_target(x, y)
        point = self._packed_point(cx, cy)
        messages = {
            "left": (0x0201, 0x0202, 0x0203, 0x0001),
            "right": (0x0204, 0x0205, 0x0206, 0x0002),
            "middle": (0x0207, 0x0208, 0x0209, 0x0010),
        }
        down, up, double, mask = messages[button]
        message = {"down": down, "up": up, "double": double}[state]
        wparam = mask if state in {"down", "double"} else 0
        if button == "left" and state in {"down", "double"} and self._class_name(hwnd) == "Button":
            self._user32.SendMessageW(hwnd, 0x00F5, 0, 0)
            return
        self._user32.SendMessageW(hwnd, 0x0200, wparam, point)
        self._user32.SendMessageW(hwnd, message, wparam, point)

    def _post_mouse_move(self, x: int, y: int, button: str) -> None:
        hwnd, cx, cy = self._mouse_target(x, y)
        mask = {"left": 0x0001, "right": 0x0002, "middle": 0x0010}[button]
        self._user32.SendMessageW(hwnd, 0x0200, mask, self._packed_point(cx, cy))

    def _post_mouse_wheel(self, x: int, y: int, amount: int, horizontal: bool) -> None:
        hwnd = int(self._user32.WindowFromPoint(_POINT(x, y)) or 0)
        if not hwnd:
            raise RuntimeError(f"No window is under mouse coordinates ({x}, {y})")
        message = 0x020E if horizontal else 0x020A
        lparam = self._packed_point(x, y)
        wparam = (amount & 0xFFFF) << 16
        self._user32.SendMessageW(hwnd, message, wparam, lparam)

    def _keyboard(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args["action"]
        if action == "type":
            text = str(args.get("text", ""))
            for char in text:
                codepoint = ord(char)
                units = (
                    [codepoint]
                    if codepoint <= 0xFFFF
                    else [
                        0xD800 + ((codepoint - 0x10000) >> 10),
                        0xDC00 + ((codepoint - 0x10000) & 0x3FF),
                    ]
                )
                for unit in units:
                    self._send_key(0, 0x0004, unit)
                    self._send_key(0, 0x0006, unit)
        elif action in {"press", "down", "up"}:
            key = str(args.get("key", "")).upper()
            vk = self._key_code(key)
            if action in {"press", "down"}:
                key_events = [(vk, 0, 0)]
            else:
                key_events = []
            if action in {"press", "up"}:
                key_events.append((vk, 0x0002, 0))
            self._send_key_events(key_events)
            target = self._focused_window()
            if not target:
                raise RuntimeError("No focused window is available for the requested key")
            if action in {"press", "down"}:
                self._post_key(target, vk, key_up=False)
            if action in {"press", "up"}:
                self._post_key(target, vk, key_up=True)
        elif action == "hotkey":
            keys = [str(key).upper() for key in args.get("keys", [])]
            if not keys:
                raise ValueError("hotkey requires keys")
            codes = [self._key_code(key) for key in keys]
            for code in codes:
                self._send_key(code, 0)
                time.sleep(0.01)
            for code in reversed(codes):
                self._send_key(code, 0x0002)
                time.sleep(0.01)
            self._post_hotkey(codes)
        else:
            raise ValueError(f"Unsupported keyboard action: {action}")
        return self._success(
            {
                "action": action,
                "foreground_window_id": int(self._user32.GetForegroundWindow() or 0),
                "text_length": len(str(args.get("text", ""))) if action == "type" else None,
            }
        )

    @staticmethod
    def _key_code(key: str) -> int:
        if key not in _KEYS:
            raise ValueError(f"Unsupported key name: {key}")
        return _KEYS[key]

    def _send_key(self, vk: int, flags: int, scan: int = 0) -> None:
        self._send_key_events([(vk, flags, scan)])

    def _send_key_events(self, events: list[tuple[int, int, int]]) -> None:
        inputs = (_INPUT * len(events))(
            *[
                _INPUT(type=1, ki=_KEYBDINPUT(vk, scan, flags, 0, None))
                for vk, flags, scan in events
            ]
        )
        if self._user32.SendInput(len(inputs), inputs, ctypes.sizeof(_INPUT)) != len(inputs):
            raise ctypes.WinError(ctypes.get_last_error())

    def _post_hotkey(self, codes: list[int]) -> None:
        target = self._focused_window()
        if not target:
            raise RuntimeError("No focused window is available for the requested hotkey")
        for code in codes:
            self._post_key(target, code, key_up=False)
        for code in reversed(codes):
            self._post_key(target, code, key_up=True)

    def _focused_window(self) -> int:
        foreground = self._user32.GetForegroundWindow()
        if not foreground:
            return 0
        thread_id = self._user32.GetWindowThreadProcessId(foreground, None)
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if not self._user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return int(foreground)
        return int(info.hwndFocus or info.hwndActive or foreground)

    def _post_key(self, target: int, vk: int, *, key_up: bool) -> None:
        scan = self._user32.MapVirtualKeyW(vk, 0)
        lparam = 1 | (scan << 16)
        if vk in {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C}:
            lparam |= 1 << 24
        message = 0x0101 if key_up else 0x0100
        if key_up:
            lparam |= (1 << 30) | (1 << 31)
        self._user32.SendMessageW(target, message, vk, lparam)

    def _clipboard(self, args: dict[str, Any]) -> dict[str, Any]:
        action = args["action"]
        if action == "write":
            text = str(args.get("text", ""))
            if not self._user32.OpenClipboard(None):
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self._user32.EmptyClipboard()
                payload = (text + "\0").encode("utf-16-le")
                memory = self._kernel32.GlobalAlloc(0x0002, len(payload))
                if not memory:
                    raise ctypes.WinError(ctypes.get_last_error())
                pointer = self._kernel32.GlobalLock(memory)
                if not pointer:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    ctypes.memmove(pointer, payload, len(payload))
                finally:
                    self._kernel32.GlobalUnlock(memory)
                if not self._user32.SetClipboardData(13, memory):
                    self._kernel32.GlobalFree(memory)
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                self._user32.CloseClipboard()
            return self._success({"action": action, "characters": len(text)})
        if action == "read":
            for _ in range(10):
                if self._user32.OpenClipboard(None):
                    break
                time.sleep(0.02)
            else:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                handle = self._user32.GetClipboardData(13)
                if not handle:
                    return self._success({"action": action, "text": ""})
                pointer = self._kernel32.GlobalLock(handle)
                if not pointer:
                    raise ctypes.WinError(ctypes.get_last_error())
                try:
                    text = ctypes.wstring_at(pointer)
                finally:
                    self._kernel32.GlobalUnlock(handle)
            finally:
                self._user32.CloseClipboard()
            return self._success({"action": action, "text": text})
        raise ValueError(f"Unsupported clipboard action: {action}")

    @staticmethod
    def _success(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "data": data,
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "is_error": False,
        }

    async def shutdown(self) -> None:
        self._closed = True
        for path in self._artifacts:
            path.unlink(missing_ok=True)
        self._artifacts.clear()
