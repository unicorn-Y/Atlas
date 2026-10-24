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

def _window() -> dict[str, str]:
    try:
        from pywinauto import Desktop
        win = Desktop(backend="uia").get_active()
        proc = ""; pid = ""
        try:
            pid = str(win.element_info.process_id)
            import ctypes
            from ctypes import wintypes
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))
            if handle:
                buffer = ctypes.create_unicode_buffer(1024); size = wintypes.DWORD(len(buffer))
                if ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                    proc = Path(buffer.value).name
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception: pass
        return {"title": str(win.window_text() or "")[:300], "process": proc, "pid": pid}
    except Exception: return {"title": "", "process": "", "pid": ""}

def _password_focused() -> bool:
    try:
        from pywinauto import Desktop
        control = Desktop(backend="uia").get_focus()
        if bool(control.element_info.control_type == "Edit" and getattr(control.element_info, "is_password", False)): return True
        labels = " ".join([str(control.window_text()), str(control.element_info.name)])
        return bool(_SENSITIVE.search(labels))
    except Exception: return False

def _window_has_sensitive_field() -> bool:
    try:
        from pywinauto import Desktop
        window=Desktop(backend="uia").get_active()
        for control in window.descendants():
            info=control.element_info
            if bool(getattr(info,"is_password",False)) or _SENSITIVE.search(str(info.name or "")):
                return True
        return False
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
    name = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:60]
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

def replay() -> dict[str, Any]:
    state=snapshot(); results=[]
    if state.get("recording"): raise ValueError("先停止录制。")
    from pynput import mouse, keyboard
    for step in state.get("steps",[]):
        expected=step.get("window") or {}; actual=_window()
        if expected.get("process") and expected.get("process").casefold()!=str(actual.get("process","")).casefold():
            results.append({"id":step.get("id"),"ok":False,"error":"目标进程不匹配"}); continue
        if step.get("action")=="click":
            if expected.get("title") and expected.get("title") not in actual.get("title",""):
                results.append({"id":step["id"],"ok":False,"error":"目标窗口标题不匹配"}); continue
            try:
                pointer=mouse.Controller(); pointer.position=(int(step["x"]),int(step["y"])); pointer.click(mouse.Button.left,1)
                time.sleep(.25); matched=_anchor_matches(str(step.get("anchor") or ""),int(step["x"]),int(step["y"]))
                results.append({"id":step["id"],"ok":matched,"anchor_checked":bool(step.get("anchor")),"error":"截图锚点不匹配" if step.get("anchor") and not matched else "截图锚点缺失" if not step.get("anchor") else ""})
            except Exception as exc: results.append({"id":step["id"],"ok":False,"error":str(exc)})
        elif step.get("action")=="key" and not str(step.get("key","")).startswith("[敏感"):
            try:
                controller=keyboard.Controller(); key=str(step["key"])
                parts=key.split("+"); key=parts[-1]
                modifier_names={"ctrl":"ctrl_l","shift":"shift_l","alt":"alt_l","cmd":"cmd_l"}
                values=[getattr(keyboard.Key,modifier_names.get(part,part)) for part in parts[:-1] if hasattr(keyboard.Key,modifier_names.get(part,part))]
                value=getattr(keyboard.Key,key.split(".",1)[1]) if key.startswith("Key.") else keyboard.KeyCode.from_char(key.strip("'"))
                for modifier in values: controller.press(modifier)
                controller.press(value); controller.release(value)
                for modifier in reversed(values): controller.release(modifier)
                time.sleep(.15); matched=_anchor_matches(str(step.get("anchor") or ""),*mouse.Controller().position)
                results.append({"id":step["id"],"ok":matched if step.get("anchor") else True,"anchor_checked":bool(step.get("anchor")),"error":"截图锚点不匹配" if step.get("anchor") and not matched else ""})
            except Exception as exc: results.append({"id":step["id"],"ok":False,"error":str(exc)})
        elif step.get("action")=="text":
            try:
                mouse_controller=mouse.Controller(); x,y=mouse_controller.position
                keyboard.Controller().type(str(step.get("text") or "")); time.sleep(.2)
                matched=_anchor_matches(str(step.get("anchor") or ""),int(x),int(y))
                results.append({"id":step["id"],"ok":matched if step.get("anchor") else True,"anchor_checked":bool(step.get("anchor")),"error":"截图锚点不匹配" if step.get("anchor") and not matched else ""})
            except Exception as exc: results.append({"id":step["id"],"ok":False,"error":str(exc)})
        else: results.append({"id":step.get("id"),"ok":True,"skipped":True,"reason":"不会自动重放敏感输入和窗口切换"})
    return {"results":results,"ok":all(row["ok"] for row in results)}
