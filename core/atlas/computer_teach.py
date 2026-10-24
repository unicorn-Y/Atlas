"""Global desktop teaching recorder. Captures demonstrations, never runs automatically."""
from __future__ import annotations
import base64, io, json, re, threading, time, uuid
from pathlib import Path
from typing import Any


_LOCK = threading.RLock()
_SESSION: dict[str, Any] | None = None
_LISTENERS: list[Any] = []
_THREAD: threading.Thread | None = None
_SENSITIVE = re.compile(r"password|passwd|token|secret|credential|card\s*(number|no\.?|security)|cvv|cvc|otp|one[- ]time|verification|验证码|密码|密钥|卡号|安全码", re.I)

def _foreground_hwnd() -> int:
    import ctypes
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def _window() -> dict[str, str]:
    # pywinauto 0.6.9 的 Desktop 没有 get_active()/get_focus()（调用会抛 AttributeError 被吞成空值），
    # 前台窗口身份直接用 Win32 API 取。
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = _foreground_hwnd()
        if not hwnd:
            return {"title": "", "process": "", "pid": ""}
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, title_buffer, length + 1)
        pid_value = wintypes.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_value))
        proc = ""
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid_value.value)
        if handle:
            buffer = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(len(buffer))
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                proc = Path(buffer.value).name
            ctypes.windll.kernel32.CloseHandle(handle)
        return {"title": title_buffer.value[:300], "process": proc, "pid": str(pid_value.value or "")}
    except Exception: return {"title": "", "process": "", "pid": ""}

def _password_focused() -> bool:
    try:
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo
        element = IUIA().iuia.GetFocusedElement()
        info = UIAElementInfo(element)
        try:
            if bool(element.CurrentIsPassword):
                return True
        except Exception:
            pass
        return bool(_SENSITIVE.search(" ".join([str(info.name or ""), str(info.automation_id or "")])))
    except Exception: return False


_SENSITIVE_WINDOW_CACHE: dict[int, tuple[float, bool]] = {}


def _window_has_sensitive_field() -> bool:
    """Whether the foreground window shows a password/credential field (cached per window for 3s:
    walking the whole UIA tree on every key press is far too slow)."""
    try:
        hwnd = _foreground_hwnd()
        cached = _SENSITIVE_WINDOW_CACHE.get(hwnd)
        if cached and time.time() - cached[0] < 3:
            return cached[1]
        from pywinauto import Desktop
        window = Desktop(backend="uia").window(handle=hwnd).wrapper_object()
        found = False
        for control in window.descendants():
            info = control.element_info
            try:
                is_password = bool(info.element.CurrentIsPassword)
            except Exception:
                is_password = False
            if is_password or _SENSITIVE.search(str(info.name or "")):
                found = True
                break
        _SENSITIVE_WINDOW_CACHE[hwnd] = (time.time(), found)
        return found
    except Exception: return False

def _cursor_anchor() -> str:
    try:
        from pynput import mouse
        x,y = mouse.Controller().position
        return _anchor(int(x),int(y))
    except Exception: return ""

def _anchor(x: int, y: int) -> str:
    try:
        import mss
        from PIL import Image
        with mss.mss() as screen:
            shot = screen.grab({"left": max(0,x-48), "top": max(0,y-36), "width": 96, "height": 72})
            image = Image.frombytes("RGB", shot.size, shot.rgb)
            output = io.BytesIO(); image.save(output, format="PNG")
            return base64.b64encode(output.getvalue()).decode("ascii")
    except Exception: return ""

def _anchor_matches(encoded: str, x: int, y: int) -> bool:
    if not encoded: return False
    try:
        from PIL import Image, ImageChops, ImageStat
        import mss
        expected=Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
        with mss.mss() as screen:
            shot=screen.grab({"left":max(0,x-48),"top":max(0,y-36),"width":96,"height":72})
            actual=Image.frombytes("RGB",shot.size,shot.rgb)
        return sum(ImageStat.Stat(ImageChops.difference(expected,actual)).mean)/3 <= 30
    except Exception: return False

def _append(action: str, **data: Any) -> None:
    with _LOCK:
        if not _SESSION or not _SESSION.get("recording"): return
        steps = _SESSION["steps"]
        previous = steps[-1] if steps else None
        # 连续打字合并成一步"输入 hello atlas"，而不是每个字符一步（空格也并进去）。
        typed = data.get("text") if action == "text" else (" " if action == "key" and data.get("key") == "Key.space" else None)
        if (typed is not None and previous is not None and previous.get("action") == "text"
                and previous.get("window") == data.get("window") and time.time() - float(previous.get("at", 0)) < 3
                and len(str(previous.get("text", ""))) < 2000):
            previous["text"] = str(previous.get("text", "")) + typed
            previous["at"] = time.time()
            return
        step = {"id": uuid.uuid4().hex[:10], "at": time.time(), "action": action, **data}
        _SESSION["steps"].append(step)
        _SESSION["count"] = len(_SESSION["steps"])

def _window_watcher(stop: threading.Event) -> None:
    previous = _window()
    while not stop.wait(.7):
        current = _window()
        if current != previous:
            _append("window", window=current)
            previous = current

def start() -> dict[str, Any]:
    global _SESSION, _LISTENERS, _THREAD
    with _LOCK:
        if _SESSION and _SESSION.get("recording"): raise ValueError("桌面教学录制已经在进行。")
        _SESSION = {"id": uuid.uuid4().hex, "recording": True, "count": 0, "steps": [], "started": time.time(), "stop_event": threading.Event()}
        state = _SESSION
    try:
        from pynput import keyboard, mouse
        modifiers: set[str] = set()
        def on_click(x: int, y: int, button: Any, pressed: bool) -> None:
            if pressed:
                w = _window(); anchor = "" if _window_has_sensitive_field() else _anchor(int(x),int(y))
                _append("click", x=int(x), y=int(y), button=str(button), window=w, anchor=anchor)
        def on_press(key: Any) -> None:
            key_name = str(key)
            modifier = key_name.replace("Key.", "").replace("_r", "").replace("_l", "")
            if modifier in {"ctrl", "alt", "shift", "cmd"}:
                modifiers.add(modifier)
                return
            sensitive = _password_focused()
            try:
                char = key.char
            except AttributeError: char = None
            text = str(char) if char else str(key)
            if text in {"Key.caps_lock"}: return
            if sensitive:
                # Never persist a character typed in a recognized credential field.
                text = "[敏感内容]"
                if _SESSION and _SESSION.get("steps") and _SESSION["steps"][-1].get("action") == "sensitive_input": return
                _append("sensitive_input", key="[内容已脱敏]", window=_window())
            elif char and not modifiers: _append("text", text=text[:80], window=_window(), anchor="" if _window_has_sensitive_field() else _cursor_anchor())
            else: _append("key", key=("+".join([*sorted(modifiers), text]) if modifiers else text)[:80], window=_window(), anchor="" if _window_has_sensitive_field() else _cursor_anchor())
        def on_release(key: Any) -> bool | None:
            modifier = str(key).replace("Key.", "").replace("_r", "").replace("_l", "")
            modifiers.discard(modifier)
            if str(key) == "Key.esc" and _SESSION and _SESSION.get("stop_event"):
                return False
            return None
        ml = mouse.Listener(on_click=on_click); kl = keyboard.Listener(on_press=on_press, on_release=on_release)
        ml.start(); kl.start(); _LISTENERS = [ml, kl]
        _THREAD = threading.Thread(target=_window_watcher, args=(state["stop_event"],), daemon=True); _THREAD.start()
    except Exception as exc:
        state["recording"] = False
        raise RuntimeError(f"桌面事件采集依赖不可用：{exc}") from exc
    return snapshot()

def snapshot() -> dict[str, Any]:
    with _LOCK:
        if not _SESSION: return {"recording": False, "count": 0, "steps": []}
        return {key: value for key,value in _SESSION.items() if key != "stop_event"}

def stop() -> dict[str, Any]:
    global _LISTENERS
    with _LOCK:
        if not _SESSION: raise ValueError("当前没有桌面教学录制。")
        _SESSION["recording"] = False
        _SESSION["stop_event"].set()
        listeners, _LISTENERS = _LISTENERS, []
    for listener in listeners:
        try: listener.stop()
        except Exception: pass
    return snapshot()

def correct(steps: list[dict[str, Any]]) -> dict[str, Any]:
    with _LOCK:
        if not _SESSION or _SESSION.get("recording"): raise ValueError("请先停止录制再校正。")
        clean=[]
        for step in steps:
            if not isinstance(step, dict): continue
            item={k:v for k,v in step.items() if k in {"id","at","action","x","y","button","key","text","window","anchor","parameter","description"}}
            if item.get("action") == "sensitive_input": item["key"]="[内容已脱敏]"; item.pop("text",None); item.pop("anchor",None)
            clean.append(item)
        _SESSION["steps"] = clean; _SESSION["count"] = len(clean)
        return snapshot()

def export_skill(name: str, purpose: str = "复用已录制的桌面操作", parameters: list[str] | None = None, generated_content: str | None = None) -> dict[str, Any]:
    from atlas.skills import SKILLS_DIR
    # 保留中文等 Unicode 字母数字（中文名会被 [^a-z0-9-] 清成空串、报"名称不能为空"），只替换路径不安全字符。
    name = re.sub(r"[^\w-]+", "-", name.strip().lower(), flags=re.UNICODE).strip("-_")[:60]
    if not name: raise ValueError("技能名称不能为空。")
    state = snapshot()
    if state.get("recording") or not state.get("steps"): raise ValueError("请停止录制并保留至少一个步骤。")
    params = parameters or []
    body=[f"# {name}", "", f"用途：{purpose}", "", "参数：" + (", ".join(params) if params else "无"), "", "## 步骤", ""]
    for i, step in enumerate(state["steps"],1):
        action = step.get("description") or step.get("action")
        if step.get("parameter"): action = str(action) + f"（参数：{step['parameter']}）"
        win = step.get("window") or {}
        locator = f"窗口 {win.get('title','')} / 进程 {win.get('process','')}" if win else "当前活动窗口"
        strategy = "控件/窗口定位优先；其次用锚点截图匹配；最后使用录制坐标。"
        body.append(f"{i}. {action}；目标：{locator}；定位：{strategy}")
    target=Path(SKILLS_DIR)/"desktop"/name
    target.mkdir(parents=True,exist_ok=True)
    content = generated_content or ("---\nname: "+name+"\ndescription: "+purpose.replace("\n"," ")+"\n---\n\n"+"\n".join(body+["", "## 重放", "", "重放前确认目标窗口及权限；每步执行后比对锚点截图。敏感字段应由用户提供，不在本技能中保存。", ""]))
    content = str(content).strip()
    if content.startswith("```"):
        content = re.sub(r"^```[^\n]*\n|\n```$", "", content).strip()
    if not content.lstrip().startswith("---") or "##" not in content: raise ValueError("模型未返回有效的 SKILL.md 草稿。")
    (target/"SKILL.md").write_text(content,encoding="utf-8")
    # Keep anchor pixels with the skill so its verifier can compare them during replay.
    (target/"anchors.json").write_text(json.dumps(state["steps"],ensure_ascii=False,indent=2),encoding="utf-8")
    return {"name":name,"path":str(target/"SKILL.md"),"steps":len(state["steps"])}

def _find_window(expected: dict[str, Any]) -> int:
    """Top-level visible window whose process name and title match the recorded target."""
    import ctypes
    from ctypes import wintypes
    want_process = str(expected.get("process") or "").casefold()
    want_title = str(expected.get("title") or "")
    found: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: Any, _lparam: Any) -> bool:
        if not ctypes.windll.user32.IsWindowVisible(hwnd):
            return True
        length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length + 1)
        if want_title and want_title not in buffer.value:
            return True
        if want_process:
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
            name = ""
            if handle:
                image = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(len(image))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                    name = Path(image.value).name.casefold()
                ctypes.windll.kernel32.CloseHandle(handle)
            if name != want_process:
                return True
        found.append(int(hwnd))
        return False

    ctypes.windll.user32.EnumWindows(callback_type(callback), 0)
    return found[0] if found else 0


def _activate(hwnd: int) -> bool:
    try:
        from pywinauto.controls.hwndwrapper import HwndWrapper
        HwndWrapper(hwnd).set_focus()
    except Exception:
        import ctypes
        ctypes.windll.user32.SetForegroundWindow(hwnd)
    time.sleep(.3)
    return _foreground_hwnd() == hwnd


def _window_matches(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    if expected.get("process") and str(expected["process"]).casefold() != str(actual.get("process", "")).casefold():
        return False
    return not expected.get("title") or str(expected["title"]) in str(actual.get("title", ""))


def _step_label(index: int, step: dict[str, Any]) -> str:
    action = step.get("action")
    if step.get("description"):
        return f"第 {index} 步：{step['description']}"
    if action == "click":
        return f"第 {index} 步：点击 ({step.get('x')}, {step.get('y')})"
    if action == "text":
        return f"第 {index} 步：输入“{str(step.get('text', ''))[:30]}”"
    if action == "key":
        return f"第 {index} 步：按键 {step.get('key')}"
    if action == "window":
        return f"第 {index} 步：切换到窗口“{(step.get('window') or {}).get('title', '')}”"
    return f"第 {index} 步：{action}"


def replay() -> dict[str, Any]:
    state=snapshot(); results=[]
    if state.get("recording"): raise ValueError("先停止录制。")
    from pynput import mouse, keyboard
    for index, step in enumerate(state.get("steps",[]), 1):
        row = {"id": step.get("id"), "index": index, "label": _step_label(index, step)}
        expected = step.get("window") or {}
        action = step.get("action")
        try:
            if action == "window" or (expected and not _window_matches(expected, _window())):
                # 先把目标窗口切到前台；找不到就失败，绝不把后续输入打进别的窗口。
                hwnd = _find_window(expected) if expected else 0
                if not hwnd or not _activate(hwnd):
                    results.append({**row, "ok": False, "error": f"没找到或无法激活目标窗口“{expected.get('title', '')}”（{expected.get('process', '')}）"})
                    if action != "window":
                        continue
                    continue
                if action == "window":
                    results.append({**row, "ok": True}); continue
            if action == "click":
                pointer=mouse.Controller(); pointer.position=(int(step["x"]),int(step["y"])); pointer.click(mouse.Button.left,1)
                time.sleep(.25); matched=_anchor_matches(str(step.get("anchor") or ""),int(step["x"]),int(step["y"]))
                results.append({**row,"ok":matched or not step.get("anchor"),"anchor_checked":bool(step.get("anchor")),"error":"截图锚点不匹配（点击处画面和录制时不一样）" if step.get("anchor") and not matched else ""})
            elif action == "key" and not str(step.get("key","")).startswith("[敏感"):
                controller=keyboard.Controller(); key=str(step["key"])
                parts=key.split("+"); key=parts[-1]
                modifier_names={"ctrl":"ctrl_l","shift":"shift_l","alt":"alt_l","cmd":"cmd_l"}
                values=[getattr(keyboard.Key,modifier_names.get(part,part)) for part in parts[:-1] if hasattr(keyboard.Key,modifier_names.get(part,part))]
                value=getattr(keyboard.Key,key.split(".",1)[1]) if key.startswith("Key.") else keyboard.KeyCode.from_char(key.strip("'"))
                for modifier in values: controller.press(modifier)
                controller.press(value); controller.release(value)
                for modifier in reversed(values): controller.release(modifier)
                time.sleep(.15)
                # 键盘步骤以"仍在目标窗口"为准；录制时的光标锚点只描述鼠标位置，不能用来判定按键是否生效。
                results.append({**row,"ok":_window_matches(expected,_window()) if expected else True,"error":"" if not expected or _window_matches(expected,_window()) else "按键后目标窗口丢失"})
            elif action == "text":
                keyboard.Controller().type(str(step.get("text") or "")); time.sleep(.2)
                results.append({**row,"ok":_window_matches(expected,_window()) if expected else True,"error":"" if not expected or _window_matches(expected,_window()) else "输入后目标窗口丢失"})
            else:
                results.append({**row,"ok":True,"skipped":True,"reason":"敏感输入不会自动重放，运行技能时由用户提供"})
        except Exception as exc:
            results.append({**row,"ok":False,"error":str(exc)})
    return {"results":results,"ok":all(item["ok"] for item in results)}
