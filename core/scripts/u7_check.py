"""U7 live-browser acceptance check. Uses disposable Chrome user-data dirs only.

Run with ``python core/scripts/u7_check.py`` from the Atlas checkout. It never
opens the user's default Chrome profile and never starts Electron.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
if not CHROME.is_file():
    raise SystemExit(f"Chrome was not found at {CHROME}")


def _chrome_for_testing() -> Path:
    """Stable Chrome 137+ ignores --load-extension, so the extension check needs Chrome for Testing.

    Uses ATLAS_U7_EXTENSION_CHROME when set; otherwise reuses (or downloads once via
    @puppeteer/browsers) a copy under ATLAS_U7_CFT_DIR, default <repo>/../_tmp/cft.
    """
    configured = os.environ.get("ATLAS_U7_EXTENSION_CHROME")
    if configured:
        return Path(configured)
    cache = Path(os.environ.get("ATLAS_U7_CFT_DIR", str(ROOT.parent / "_tmp" / "cft")))
    found = sorted(cache.glob("chrome/win64-*/chrome-win64/chrome.exe"))
    if found:
        return found[-1]
    import shutil
    import subprocess as _sp
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if npx is None:
        return CHROME
    _sp.run([npx, "-y", "@puppeteer/browsers", "install", "chrome@stable", "--path", str(cache)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900, check=False)
    found = sorted(cache.glob("chrome/win64-*/chrome-win64/chrome.exe"))
    return found[-1] if found else CHROME


EXTENSION_CHROME = _chrome_for_testing()
SKIP_SCREENSHOTS = os.environ.get("ATLAS_U7_SKIP_SCREENSHOTS") == "1"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def http_json(url: str, *, method: str = "GET") -> Any:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_port_file(profile: Path, process: subprocess.Popen, timeout: float = 25) -> tuple[str, str]:
    path = profile / "DevToolsActivePort"
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if process.poll() is not None:
            raise RuntimeError("Chrome exited before starting the CDP endpoint")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            if len(lines) > 1 and lines[0].isdigit():
                return lines[0], lines[1]
        except OSError:
            pass
        time.sleep(0.2)
    raise TimeoutError("Chrome did not write DevToolsActivePort")


def launch_chrome(profile: Path, *, extension: bool = False) -> tuple[subprocess.Popen, str, str]:
    binary = EXTENSION_CHROME if extension else CHROME
    if not binary.is_file():
        raise SystemExit(f"Chrome for extension check was not found at {binary}; set ATLAS_U7_EXTENSION_CHROME to Chrome for Testing (the installed Chrome 137+ blocks --load-extension).")
    profile.mkdir(parents=True, exist_ok=True)
    args = [str(binary), f"--user-data-dir={profile}", "--remote-debugging-port=0",
            "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
            "--disable-gpu", "--no-sandbox", "about:blank"]
    if extension:
        args[-1:-1] = [f"--load-extension={ROOT / 'browser-extension'}", "--window-position=-32000,-32000"]
    else:
        args.insert(-1, "--headless=new")
    process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    port, browser_path = wait_port_file(profile, process)
    return process, port, browser_path


def close_process(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=4)


def new_target(port: str, url: str) -> dict[str, Any]:
    quoted = urllib.parse.quote(url, safe=":/?=&%#")
    return http_json(f"http://127.0.0.1:{port}/json/new?{quoted}", method="PUT")


def cdp_call(ws_url: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    from websockets.sync.client import connect
    with connect(ws_url, open_timeout=6, close_timeout=2, max_size=16_000_000) as ws:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            try:
                response = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            if response.get("id") == 1:
                if "error" in response:
                    raise RuntimeError(response["error"])
                return response.get("result") or {}
    raise TimeoutError(f"CDP command {method} returned no response")


def navigate_and_wait_network_failure(ws_url: str, url: str) -> str:
    """Capture Chromium's Network.loadingFailed error for a navigation on one CDP socket."""
    from websockets.sync.client import connect
    with connect(ws_url, open_timeout=6, close_timeout=2, max_size=2_000_000) as ws:
        failed: list[str] = []

        def send_and_wait(command_id: int, method: str, params: dict[str, Any] | None = None) -> None:
            ws.send(json.dumps({"id": command_id, "method": method, "params": params or {}}))
            until = time.monotonic() + 8
            while time.monotonic() < until:
                try:
                    message = json.loads(ws.recv(timeout=2))
                except TimeoutError:
                    continue
                # A fast DNS failure can arrive before Page.navigate's reply; keep it.
                if message.get("method") == "Network.loadingFailed":
                    failed.append(str((message.get("params") or {}).get("errorText") or ""))
                if message.get("id") == command_id:
                    if method == "Page.navigate":
                        error_text = str((message.get("result") or {}).get("errorText") or "")
                        if error_text:
                            failed.append(error_text)
                    return
        send_and_wait(1, "Network.enable")
        send_and_wait(2, "Page.enable")
        send_and_wait(3, "Page.navigate", {"url": url})
        if failed:
            return failed[0]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                event = json.loads(ws.recv(timeout=2))
            except TimeoutError:
                continue
            if event.get("method") == "Network.loadingFailed":
                return str((event.get("params") or {}).get("errorText") or "")
    return ""


def target_for(port: str, url_prefix: str | None = None) -> dict[str, Any]:
    targets = http_json(f"http://127.0.0.1:{port}/json/list")
    for target in targets:
        if target.get("type") == "page" and (url_prefix is None or str(target.get("url", "")).startswith(url_prefix)):
            return target
    raise RuntimeError("No matching Chrome page target was listed")


def evaluate(target: dict[str, Any], expression: str) -> Any:
    result = cdp_call(target["webSocketDebuggerUrl"], "Runtime.evaluate",
                      {"expression": expression, "returnByValue": True, "awaitPromise": True})
    return (result.get("result") or {}).get("value")


def wait_title(target: dict[str, Any], expected: str, timeout: float = 15) -> None:
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if evaluate(target, "document.title") == expected:
            return
        time.sleep(0.25)
    raise AssertionError(f"Chrome page did not reach title {expected!r}")


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="atlas-u7-check-"))
    data_dir = scratch / "atlas-data"
    atlas_home = scratch / "atlas-home"
    data_dir.mkdir()
    atlas_home.mkdir()
    os.environ["ATLAS_DATA_DIR"] = str(data_dir)
    os.environ["ATLAS_HOME"] = str(atlas_home)
    os.environ["ATLAS_BROWSER_PROFILE_DIR"] = str(scratch / "source-profile")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    with socket.socket() as bridge_probe:
        bridge_probe.bind(("127.0.0.1", 0))
        os.environ["ATLAS_BROWSER_EXTENSION_PORT"] = str(bridge_probe.getsockname()[1])

    from atlas.config import load_user_settings, save_user_settings
    from atlas.engine_core.tools import browser_tool_real_profile as real_profile
    from atlas.engine_core.tools.browser_extension_bridge import call_extension, connection_info
    from atlas.engine_core.tools.browser_extension_router import routed_browser_handler
    from atlas.engine_core.tools.browser_tool_vision import _analyze_screenshot_with_aux_llm
    from atlas.models.router import _anthropic_payload
    from types import SimpleNamespace

    launched: list[subprocess.Popen] = []
    try:
        # Seed a disposable Chromium user-data dir, then run the Atlas copy lane.
        seed, _, _ = launch_chrome(Path(os.environ["ATLAS_BROWSER_PROFILE_DIR"]))
        close_process(seed)
        settings = load_user_settings()
        settings["browser"] = {"mode": "copied-profile", "profile_browser": "chrome", "profile": "Default",
                               "profile_sync_interval_minutes": 10}
        save_user_settings(settings)
        cdp, error = real_profile._real_profile_cdp()
        check(bool(cdp) and error is None, f"real_profile: {error}")
        port = cdp.rsplit(":", 1)[1]
        page = new_target(port, "https://example.com")
        wait_title(page, "Example Domain")
        check(bool(evaluate(page, "document.body.innerText.includes('documentation examples')")), "real_profile snapshot did not contain page text")
        if not SKIP_SCREENSHOTS:
            screenshot = cdp_call(page["webSocketDebuggerUrl"], "Page.captureScreenshot", {"format": "png"})
            check(len(base64.b64decode(screenshot["data"])) > 1000, "real_profile screenshot was empty")
            print("real_profile PASS: copied disposable profile, Chrome launch, CDP, title, snapshot, screenshot")
        else:
            print("real_profile PASS: copied disposable profile, Chrome launch, CDP and title; screenshot capture skipped")
        close_process(real_profile._origin()._real_profile_chrome_procs[-1])
        real_profile._origin()._real_profile_chrome_procs.clear()

        # Simulate a user Chrome that explicitly opted into debugging on a temporary profile.
        live_profile = scratch / "live-chrome-profile"
        live, live_port, live_browser_path = launch_chrome(live_profile)
        launched.append(live)
        settings = load_user_settings()
        settings["browser"] = {"mode": "live_chrome", "profile_browser": "chrome"}
        save_user_settings(settings)
        os.environ["ATLAS_BROWSER_PROFILE_DIR"] = str(live_profile)
        endpoint, error = real_profile.live_chrome_cdp()
        check(endpoint == f"http://127.0.0.1:{live_port}" and not error, f"live Chrome discovery failed: {error}")
        target_for(live_port)
        fresh = new_target(live_port, "https://example.com")
        wait_title(fresh, "Example Domain")
        check(bool(target_for(live_port)), "live Chrome did not list its page targets")
        close_port = urllib.request.Request(f"http://127.0.0.1:{live_port}/json/close/{fresh['id']}", method="GET")
        with urllib.request.urlopen(close_port, timeout=4):
            pass
        reconnect, reconnect_error = real_profile.live_chrome_cdp()
        check(reconnect == endpoint and reconnect_error is None, "live Chrome did not reconnect after target close")
        print(f"live_chrome PASS: DevToolsActivePort {live_port}, listed tabs, new tab, reconnect")

        close_process(live)
        launched.remove(live)
        settings["browser"] = {"mode": "auto", "profile_browser": "chrome", "profile": "Default"}
        save_user_settings(settings)
        os.environ["ATLAS_BROWSER_PROFILE_DIR"] = str(live_profile)
        auto_profile, auto_profile_error = real_profile._real_profile_cdp()
        check(bool(auto_profile) and auto_profile_error is None
              and real_profile._origin()._real_profile_cdp_cache.get("lane") == "real_profile",
              f"auto mode skipped the copied profile: {auto_profile_error}")
        real_profile._terminate_real_profile_chrome()
        real_profile._origin()._real_profile_cdp_cache.clear()
        os.environ["ATLAS_BROWSER_PROFILE_DIR"] = str(scratch / "missing-profile")
        auto_isolated, auto_isolated_error = real_profile._real_profile_cdp()
        check(auto_isolated is None and auto_isolated_error is None
              and real_profile._origin()._real_profile_cdp_cache.get("lane") == "atlas"
              and real_profile._origin()._real_profile_cdp_cache.get("fallback_warning"),
              "auto mode did not expose its final isolated-browser fallback")
        print("auto PASS: extension > live Chrome > copied profile > isolated browser, with fallback reason")

        # Load the real unpacked extension into another disposable Chrome and pair it
        # through its actual popup, then exercise the debugger relay against a tab.
        extension_profile = scratch / "extension-chrome-profile"
        extension_browser, extension_port, _ = launch_chrome(extension_profile, extension=True)
        launched.append(extension_browser)
        info = connection_info()
        workers_until = time.monotonic() + 12
        extension_id = ""
        while time.monotonic() < workers_until:
            workers = http_json(f"http://127.0.0.1:{extension_port}/json/list")
            for worker in (item for item in workers if item.get("type") == "service_worker"
                           and str(item.get("url", "")).startswith("chrome-extension://")):
                try:
                    if evaluate(worker, "chrome.runtime.getManifest().name") == "Atlas Browser Control":
                        extension_id = worker["url"].split("/")[2]
                        break
                except Exception:
                    continue
            if extension_id:
                break
            time.sleep(0.25)
        check(bool(extension_id), "Chrome for Testing did not load browser-extension service worker")
        new_target(extension_port, "data:text/html,<title>U7 extension</title><button id='go' onclick=\"document.body.dataset.clicked='yes'\">click me</button>")
        new_target(extension_port, f"chrome-extension://{extension_id}/popup.html")
        popup_page = target_for(extension_port, f"chrome-extension://{extension_id}/popup.html")
        page_ready = time.monotonic() + 10
        while time.monotonic() < page_ready:
            if evaluate(popup_page, "document.readyState === 'complete' && !!document.querySelector('#pair')"):
                break
            time.sleep(0.2)
        else:
            raise AssertionError("Chrome did not load the Atlas extension popup page")
        cdp_call(popup_page["webSocketDebuggerUrl"], "Runtime.evaluate", {"expression": f"document.querySelector('#bridge').value='{info['url']}';document.querySelector('#code').value='{info['pairing_code']}';document.querySelector('#pair').click()"})
        time.sleep(1.2)
        if not connection_info()["connected"]:
            popup_state = evaluate(popup_page, "document.querySelector('#state')?.textContent")
            pairing_storage = evaluate(popup_page, "chrome.storage.local.get(['token','paired']).then(x=>({hasToken:!!x.token,paired:x.paired}))")
            raise AssertionError(f"Extension popup pairing did not connect: {popup_state}; storage={pairing_storage}")
        options = evaluate(popup_page, "Array.from(document.querySelector('#tabs').options).map(o=>({value:o.value,label:o.textContent}))")
        page_option = next((item for item in options if "U7 extension" in item["label"]), None)
        check(page_option is not None, f"extension popup did not list the test page: {options}")
        cdp_call(popup_page["webSocketDebuggerUrl"], "Runtime.evaluate", {"expression": f"document.querySelector('#tabs').value='{page_option['value']}';document.querySelector('#attach').click()"})
        attach_deadline = time.monotonic() + 8
        attached = None
        while time.monotonic() < attach_deadline:
            attached = evaluate(popup_page, "chrome.runtime.sendMessage({type:'state'}).then(x=>({tabId:x.tabId,connected:x.connected}))")
            if attached and attached.get("tabId"):
                break
            time.sleep(0.25)
        check(bool(attached and attached.get("tabId")), f"extension did not attach to the selected tab: {attached}")
        nav_result = call_extension("browser_navigate", {"url": "data:text/html,<title>Atlas extension tab</title><button id='go' onclick=\"document.body.dataset.clicked='yes'\">Click me</button>"})
        check(bool(nav_result.get("success")), f"extension navigate failed: {nav_result.get('error')}")
        snap = call_extension("browser_snapshot", {})
        check("@e1" in snap["data"]["snapshot"], "extension snapshot did not expose element refs")
        check(call_extension("browser_click", {"ref": "@e1"})["success"], "extension click failed")
        clicked = call_extension("browser_snapshot", {})
        check("yes" in clicked["data"]["snapshot"], "extension click did not affect the page")
        print("extension PASS: MV3 loaded, paired through popup, attached tab, navigate/click/snapshot")

        settings = load_user_settings()
        settings.setdefault("browser", {})["mode"] = "auto"
        save_user_settings(settings)
        routed = routed_browser_handler("browser_snapshot", {}, fallback=lambda: {"success": False, "error": "fallback used"})
        check("\"browser_target\": \"extension\"" in routed, "auto routing did not prioritize the connected extension")
        from atlas.engine_core.tools.browser_extension_bridge import disconnect
        close_process(extension_browser)
        disconnect()
        settings = load_user_settings()
        settings.setdefault("browser", {})["mode"] = "extension"
        save_user_settings(settings)
        try:
            routed_browser_handler("browser_snapshot", {}, fallback=lambda: {"fallback": True})
        except RuntimeError as exc:
            check("disconnected" in str(exc).lower(), "extension disconnection error was unclear")
        else:
            raise AssertionError("extension disconnect silently fell back to another browser")
        print("routing PASS: extension priority and disconnect fail-closed")

        if not SKIP_SCREENSHOTS:
            # The default Atlas config used by this isolated check intentionally has no
            # auxiliary vision model. Verify its explicit setup guidance and Anthropic image conversion.
            image = scratch / "shot.png"
            image.write_bytes(base64.b64decode(screenshot["data"]))
            vision_error = _analyze_screenshot_with_aux_llm(image, "What is visible?")
            check("没有配置视觉模型" in vision_error, "unconfigured vision model did not produce setup guidance")
        if not SKIP_SCREENSHOTS:
            import atlas.config as atlas_config
            import atlas.models as atlas_models
            captured_vision: dict[str, Any] = {}
            class FakeVisionRouter:
                async def complete_for(self, model_id: str, purpose: str, messages: list[dict[str, Any]], **_: Any) -> Any:
                    captured_vision.update(model_id=model_id, purpose=purpose, messages=messages)
                    return SimpleNamespace(text="vision route ok")
            class FakeVisionManager:
                def __init__(self) -> None:
                    self.model_router = FakeVisionRouter()
            class FakeAtlasConfig(dict):
                db_path = str(scratch / "atlas-data" / "config" / "atlas.db")
            original_config = atlas_config.get_config
            original_manager = atlas_models.ModelManager
            atlas_config.get_config = lambda: FakeAtlasConfig({"computer_use.aux_vision_model": "vision-u7-test"})
            atlas_models.ModelManager = FakeVisionManager
            try:
                routed_vision = _analyze_screenshot_with_aux_llm(image, "What is visible?")
            finally:
                atlas_config.get_config = original_config
                atlas_models.ModelManager = original_manager
            image_block = captured_vision["messages"][0]["content"][1]
            check(routed_vision == "vision route ok" and captured_vision["model_id"] == "vision-u7-test"
                  and captured_vision["purpose"] == "vision" and image_block["type"] == "image_url"
                  and image_block["image_url"]["url"].startswith("data:image/png;base64,"),
                  "configured auxiliary vision model was not sent the screenshot")
            route = SimpleNamespace(wire_model="claude-test", model="claude-test", capabilities={}, provider="anthropic")
            payload = _anthropic_payload(route, [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}]}], {})
            check(payload["messages"][0]["content"][0]["source"]["type"] == "base64", "Anthropic image block conversion failed")
            print("vision PASS: configured vision route receives screenshot; missing model is explicit; Anthropic image blocks are encoded")
        else:
            print("vision PASS: skipped because ATLAS_U7_SKIP_SCREENSHOTS=1")

        # Exercise a real Chrome DNS failure and the richer user-facing classifier.
        dns_browser, dns_port, _ = launch_chrome(scratch / "dns-failure-profile")
        launched.append(dns_browser)
        bad = new_target(dns_port, "about:blank")
        dns_url = "http://atlas-u7-nonexistent.invalid"
        dns_detail = navigate_and_wait_network_failure(bad["webSocketDebuggerUrl"], dns_url)
        if not dns_detail:
            # Some Chromium builds paint the interstitial before forwarding the
            # Network.loadingFailed event on a short-lived CDP connection.
            # The renderer may be busy while the interstitial is initializing;
            # do not block on Runtime.evaluate here. Reattach to CDP and observe
            # the navigation event again instead.
            try:
                body = str(evaluate(bad, "document.body.innerText") or "")
            except TimeoutError:
                body = ""
            if "ERR_NAME_NOT_RESOLVED" in body:
                dns_detail = "net::ERR_NAME_NOT_RESOLVED"
        if not dns_detail:
            # A few builds lose the first failing event while opening the network error page.
            dns_detail = navigate_and_wait_network_failure(bad["webSocketDebuggerUrl"], dns_url)
        from atlas.engine_core.tools.browser_tool import _explain_navigation_error
        error_text = _explain_navigation_error(dns_detail or "net::ERR_NAME_NOT_RESOLVED")
        check(bool(dns_detail) and (dns_detail in error_text or "DNS" in error_text),
              f"Chrome did not surface a specific network result: cdp={dns_detail!r}; diagnosis={error_text!r}")
        print(f"load failure PASS: real Chrome {dns_detail or 'DNS'} result plus actionable diagnosis")

        from atlas.engine_core.tools.browser_tool_session import _apply_incognito_arg
        private_env = {"AGENT_BROWSER_ARGS": "--disable-dev-shm-usage"}
        _apply_incognito_arg(private_env, {"features": {"local": True}}, True)
        check("--incognito" in private_env["AGENT_BROWSER_ARGS"], "standalone private mode did not request Chromium incognito")
        attached_env = {"AGENT_BROWSER_ARGS": ""}
        _apply_incognito_arg(attached_env, {"cdp_url": endpoint, "features": {"live_chrome": True}}, True)
        check("--incognito" not in attached_env["AGENT_BROWSER_ARGS"], "private mode modified a user-owned Chrome session")
        print("incognito PASS: isolated browser gets a private context; attached user browsers are untouched")
    finally:
        try:
            real_profile._terminate_real_profile_chrome()
        except Exception:
            pass
        for process in reversed(launched):
            close_process(process)
        try:
            shutil.rmtree(scratch, ignore_errors=True)
        except OSError:
            pass
    print("U7 CHECK PASS")


if __name__ == "__main__":
    main()
