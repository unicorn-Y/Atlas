"""Platform-gated Android and iOS simulator tools.

Behavioral reference: ZCode@aac4755666d09fdcd70272fcf063c077a639015f
`android-emulator-plugin/src/mcp/server.ts`, `android-emulator-plugin/src/providers/ui.ts`,
`ios-simulator-plugin/src/mcp/server.ts`, and the iOS simulator provider modules.
This is an independent subprocess adapter; no upstream source code is copied.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import uuid
from pathlib import Path
from typing import Any


def _prop(kind: str, description: str = "", **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {"type": kind}
    if description:
        value["description"] = description
    value.update(extra)
    return value


_ANDROID_TARGET = {
    "serial": _prop("string", "Android device or emulator serial."),
    "avd": _prop("string", "AVD name to start when no ready device is selected."),
    "timeoutMs": _prop("integer", "Operation timeout in milliseconds.", minimum=1),
}
_IOS_TARGET = {
    "udid": _prop("string", "Simulator UDID."),
    "device": _prop("string", "Simulator device name fragment."),
    "runtime": _prop("string", "Simulator runtime name fragment."),
}
_ANDROID_BUILD = {
    **_ANDROID_TARGET,
    "projectDir": _prop("string", "Gradle project root relative to the active workspace."),
    "module": _prop("string", "Gradle module; defaults to app."),
    "variant": _prop("string", "Build variant; defaults to debug."),
    "applicationId": _prop("string", "Override discovered Android application ID."),
}
_IOS_BUILD = {
    **_IOS_TARGET,
    "project": _prop("string", "Relative .xcodeproj path."),
    "workspace": _prop("string", "Relative .xcworkspace path."),
    "scheme": _prop("string", "Xcode scheme."),
    "configuration": _prop("string", "Build configuration; defaults to Debug."),
    "derivedDataPath": _prop("string", "DerivedData directory relative to workspace."),
    "bundleId": _prop("string", "Override discovered bundle identifier."),
    "openSimulator": _prop("boolean", "Open the Simulator app after build."),
    "timeoutMs": _prop("integer", "Build timeout in milliseconds.", minimum=1),
}


def _spec(name: str, description: str, properties: dict[str, Any] | None = None,
          required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {
            "type": "object", "properties": properties or {},
            "required": required or [], "additionalProperties": False,
        },
    }}


_SPECS = [
    _spec("android_preflight", "Check Android SDK, adb, emulator, Java, Gradle and UI Automator availability."),
    _spec("android_discover_project", "Find Android Gradle root, modules, package ID and APK outputs."),
    _spec("android_create_app", "Create a minimal Kotlin Android app in the active workspace.", {
        "name": _prop("string"), "packageName": _prop("string"), "dir": _prop("string"),
        "minSdk": _prop("integer", minimum=1),
    }, ["name"]),
    _spec("android_build_app", "Build the current or selected Android Gradle project.", _ANDROID_BUILD),
    _spec("android_build_and_run", "Build an Android app, install it and launch it on a ready or newly started emulator.", {
        **_ANDROID_BUILD, "launchActivity": _prop("string"),
    }),
    _spec("android_list_devices", "List Android devices and emulators visible to adb."),
    _spec("android_list_avds", "List installed Android Virtual Devices."),
    _spec("android_start_emulator", "Start a GUI Android emulator for an AVD.", {
        "avd": _prop("string"), "timeoutMs": _prop("integer", minimum=1),
    }),
    _spec("android_stop_emulator", "Stop an Android emulator by serial.", {"serial": _prop("string")}, ["serial"]),
    _spec("android_create_avd", "Create an Android Virtual Device; SDK images must already be installed.", {
        "name": _prop("string"), "packageId": _prop("string"), "device": _prop("string"), "force": _prop("boolean"),
    }),
    _spec("android_install_app", "Install an APK on an Android device or emulator.", {
        **_ANDROID_TARGET, "apkPath": _prop("string", "APK path inside the active workspace."),
    }, ["apkPath"]),
    _spec("android_launch_app", "Launch an installed Android application.", {
        **_ANDROID_TARGET, "applicationId": _prop("string"), "activity": _prop("string"),
    }, ["applicationId"]),
    _spec("android_terminate_app", "Force-stop an Android application.", {
        **_ANDROID_TARGET, "applicationId": _prop("string"),
    }, ["applicationId"]),
    _spec("android_open_url", "Open an HTTP(S) or app URL on an Android device.", {
        **_ANDROID_TARGET, "url": _prop("string"),
    }, ["url"]),
    _spec("android_screenshot", "Capture a screenshot from an Android device into the workspace.", {
        **_ANDROID_TARGET, "path": _prop("string"),
    }),
    _spec("android_logs", "Read recent Android logcat output.", {
        **_ANDROID_TARGET, "applicationId": _prop("string"),
        "lines": _prop("integer", minimum=1, maximum=5000), "limit": _prop("integer", minimum=1, maximum=5000),
    }),
    _spec("android_ui_status", "Check adb-backed UI Automator availability."),
    _spec("android_ui_describe", "Describe visible Android UI Automator elements.", _ANDROID_TARGET),
    _spec("android_ui_resolve", "Find a visible Android UI element by text, content description or resource ID.", {
        **_ANDROID_TARGET, "query": _prop("string"),
    }, ["query"]),
    _spec("android_ui_tap", "Tap Android screen coordinates.", {
        **_ANDROID_TARGET, "x": _prop("number"), "y": _prop("number"),
    }, ["x", "y"]),
    _spec("android_ui_swipe", "Swipe Android screen coordinates.", {
        **_ANDROID_TARGET, "x1": _prop("number"), "y1": _prop("number"),
        "x2": _prop("number"), "y2": _prop("number"), "durationMs": _prop("integer", minimum=1),
    }, ["x1", "y1", "x2", "y2"]),
    _spec("android_ui_type_text", "Type text into the focused Android UI; input is limited to 1000 characters.", {
        **_ANDROID_TARGET, "text": _prop("string"),
    }, ["text"]),
    _spec("android_ui_keyevent", "Send a supported Android key event.", {
        **_ANDROID_TARGET, "key": _prop("string", "Supported Android system key event.",
                                         enum=["BACK", "HOME", "ENTER", "APP_SWITCH", "MENU", "SEARCH"]),
    }, ["key"]),
    _spec("ios_preflight", "Check macOS, full Xcode, simctl, simulator runtimes and optional idb UI control."),
    _spec("ios_list_simulators", "List iOS simulators visible to xcrun simctl."),
    _spec("ios_boot_simulator", "Boot an iOS simulator and optionally open the Simulator app.", {
        **_IOS_TARGET, "openSimulator": _prop("boolean"),
    }),
    _spec("ios_show_simulator", "Open Simulator and focus an optional UDID.", {"udid": _prop("string")}),
    _spec("ios_discover_project", "Find Xcode projects, workspaces and schemes in the active workspace."),
    _spec("ios_create_app", "Create a minimal SwiftUI app and XcodeGen project in the active workspace.", {
        "name": _prop("string"), "bundleId": _prop("string"), "dir": _prop("string"),
        "deployment": _prop("string"),
    }, ["name"]),
    _spec("ios_build_app", "Build an iOS Simulator app with xcodebuild.", _IOS_BUILD),
    _spec("ios_build_and_run", "Build, install and launch an iOS Simulator app.", {
        **_IOS_BUILD, "launchArgs": _prop("array", items={"type": "string"}),
    }),
    _spec("ios_install_app", "Install an .app bundle on an iOS simulator.", {
        **_IOS_TARGET, "appPath": _prop("string", "App bundle path inside the active workspace."),
    }, ["appPath"]),
    _spec("ios_launch_app", "Launch an installed iOS application.", {
        **_IOS_TARGET, "bundleId": _prop("string"), "launchArgs": _prop("array", items={"type": "string"}),
    }, ["bundleId"]),
    _spec("ios_terminate_app", "Terminate an iOS application on a simulator.", {
        **_IOS_TARGET, "bundleId": _prop("string"),
    }, ["bundleId"]),
    _spec("ios_open_url", "Open a URL on an iOS simulator.", {**_IOS_TARGET, "url": _prop("string")}, ["url"]),
    _spec("ios_screenshot", "Capture a screenshot from an iOS simulator into the workspace.", {
        **_IOS_TARGET, "path": _prop("string"), "openSimulator": _prop("boolean"),
    }),
    _spec("ios_logs", "Read recent iOS simulator unified logs.", {
        **_IOS_TARGET, "bundleId": _prop("string"), "seconds": _prop("integer", minimum=1),
        "limit": _prop("integer", minimum=1, maximum=5000),
    }),
    _spec("ios_ui_status", "Check optional idb UI automation availability."),
    _spec("ios_ui_tap", "Tap iOS Simulator coordinates through idb.", {
        **_IOS_TARGET, "x": _prop("number"), "y": _prop("number"), "duration": _prop("number", minimum=0),
    }, ["x", "y"]),
    _spec("ios_ui_swipe", "Swipe iOS Simulator coordinates through idb.", {
        **_IOS_TARGET, "x1": _prop("number"), "y1": _prop("number"),
        "x2": _prop("number"), "y2": _prop("number"), "delta": _prop("number", minimum=0),
    }, ["x1", "y1", "x2", "y2"]),
    _spec("ios_ui_type_text", "Type text in iOS Simulator through idb.", {
        **_IOS_TARGET, "text": _prop("string"),
    }, ["text"]),
    _spec("ios_ui_button", "Press an idb simulator hardware button such as HOME or LOCK.", {
        **_IOS_TARGET, "button": _prop("string", enum=["APPLE_PAY", "HOME", "LOCK", "SIDE_BUTTON", "SIRI"]),
        "duration": _prop("number", minimum=0),
    }, ["button"]),
    _spec("ios_ui_describe", "Describe visible iOS Simulator UI through optional idb.", _IOS_TARGET),
]

MOBILE_READ_ONLY_TOOLS = frozenset({
    "android_preflight", "android_discover_project", "android_list_devices", "android_list_avds",
    "android_logs", "android_ui_status", "android_ui_describe", "android_ui_resolve",
    "ios_preflight", "ios_list_simulators", "ios_discover_project", "ios_logs", "ios_ui_status",
    "ios_ui_describe",
})
MOBILE_MUTATING_TOOLS = frozenset(
    str(item["function"]["name"]) for item in _SPECS
    if str(item["function"]["name"]) not in MOBILE_READ_ONLY_TOOLS
)


def mobile_tool_schemas() -> list[dict[str, Any]]:
    available = [
        item for item in _SPECS
        if (not str(item["function"]["name"]).startswith("ios_") or sys.platform == "darwin")
        and (not str(item["function"]["name"]).startswith("android_") or sys.platform in {"darwin", "win32"})
    ]
    return json.loads(json.dumps(available))


async def call_mobile_tool(name: str, arguments: dict[str, Any], workspace: str) -> dict[str, Any]:
    return await asyncio.to_thread(_call_mobile_tool, name, dict(arguments), workspace)


def _result(command: list[str], *, cwd: Path | None = None,
            timeout: float = 30, binary: bool = False) -> subprocess.CompletedProcess[Any]:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=not binary,
                          encoding=None if binary else "utf-8",
                          errors=None if binary else "replace",
                          timeout=max(1, min(timeout, 600)), shell=False)


def _screenshot_result(path: Path, *, device_key: str, device_id: str) -> dict[str, Any]:
    image = path.read_bytes()
    data: dict[str, Any] = {"captured": True, device_key: device_id, "path": str(path)}
    if len(image) <= 8 * 1024 * 1024:
        data["_image_data_url"] = "data:image/png;base64," + base64.b64encode(image).decode("ascii")
    else:
        data["image_omitted_reason"] = "Screenshot exceeds the 8 MiB model image limit."
    return {"content": [{"type": "text", "text": f"Screenshot saved to {path}"}], "data": data}


def _tool_path(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    sdk = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if sdk:
        base = Path(sdk)
        candidates = {
            "adb": [base / "platform-tools" / "adb.exe", base / "platform-tools" / "adb"],
            "emulator": [base / "emulator" / "emulator.exe", base / "emulator" / "emulator"],
            "sdkmanager": [base / "cmdline-tools" / "latest" / "bin" / "sdkmanager.bat",
                           base / "cmdline-tools" / "latest" / "bin" / "sdkmanager"],
            "avdmanager": [base / "cmdline-tools" / "latest" / "bin" / "avdmanager.bat",
                           base / "cmdline-tools" / "latest" / "bin" / "avdmanager"],
        }.get(name, [])
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def _timeout_seconds(arguments: dict[str, Any], default_ms: int) -> float:
    timeout_ms = int(arguments.get("timeoutMs") or default_ms)
    return max(1, min(timeout_ms, 600_000)) / 1000


def _workspace_path(workspace: str, value: str | None = None) -> Path:
    root = Path(workspace).expanduser().resolve()
    candidate = (root / value).resolve() if value else root
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("Path must remain inside the active workspace.") from exc
    return candidate


def _run_checked(command: list[str], *, cwd: Path | None = None,
                 timeout: float = 30, max_chars: int = 16000) -> str:
    result = _result(command, cwd=cwd, timeout=timeout)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode:
        raise RuntimeError(output.strip()[-max_chars:] or f"Command failed ({result.returncode}).")
    return output[-max_chars:]


def _android_sdk_status() -> dict[str, Any]:
    names = ["adb", "emulator", "sdkmanager", "avdmanager", "java", "gradle"]
    found = {name: _tool_path(name) for name in names}
    root = os.environ.get("ANDROID_SDK_ROOT") or os.environ.get("ANDROID_HOME")
    if not root and found["adb"]:
        root = str(Path(found["adb"]).resolve().parent.parent)
    return {"platform": platform.system(), "sdk_root": root, "tools": found,
            "available": bool(found["adb"] and found["emulator"])}


def _adb(serial: str | None, *args: str, timeout: float = 30, binary: bool = False) -> Any:
    adb = _tool_path("adb")
    if not adb:
        raise RuntimeError("Android adb is unavailable; install Android platform-tools and set ANDROID_SDK_ROOT.")
    command = [adb]
    if serial:
        command.extend(["-s", serial])
    command.extend(args)
    result = _result(command, timeout=timeout, binary=binary)
    if result.returncode:
        detail = result.stderr if binary is False else b""
        raise RuntimeError(str(detail or "adb command failed").strip())
    return result


def _android_devices(*, timeout: float = 30) -> list[dict[str, str]]:
    output = _adb(None, "devices", "-l", timeout=timeout).stdout
    rows = []
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2:
            rows.append({"serial": parts[0], "state": parts[1], "details": " ".join(parts[2:])})
    return rows


def _android_serial(arguments: dict[str, Any]) -> str:
    requested = str(arguments.get("serial") or "")
    timeout = _timeout_seconds(arguments, 180_000)
    devices = _android_devices(timeout=timeout)
    if requested:
        if not any(item["serial"] == requested and item["state"] == "device" for item in devices):
            raise RuntimeError(f"Android device is not ready: {requested}")
        if requested.startswith("emulator-"):
            _wait_android_boot(requested, timeout)
        return requested
    ready = next((item["serial"] for item in devices
                  if item["state"] == "device" and item["serial"].startswith("emulator-")), None)
    ready = ready or next((item["serial"] for item in devices if item["state"] == "device"), None)
    if ready:
        if ready.startswith("emulator-"):
            _wait_android_boot(ready, timeout)
        return ready
    started = _android_start(arguments)
    return str(started["serial"])


def _wait_android_boot(serial: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if str(_adb(serial, "shell", "getprop", "sys.boot_completed", timeout=10).stdout).strip() == "1":
                return
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for Android Emulator to boot ({serial}).")


def _android_avd_name(serial: str, *, timeout: float = 8) -> str:
    output = str(_adb(serial, "emu", "avd", "name", timeout=timeout).stdout)
    return next((line.strip() for line in output.splitlines()
                 if line.strip() and line.strip() != "OK"), "")


def _android_project(workspace: str, arguments: dict[str, Any]) -> Path:
    root = _workspace_path(workspace, str(arguments.get("projectDir") or "."))
    if not root.is_dir():
        raise ValueError(f"Android project directory not found: {root}")
    return root


def _android_discover(workspace: str) -> dict[str, Any]:
    root = Path(workspace).resolve()
    hits: list[dict[str, Any]] = []
    ignored = {".git", ".gradle", ".idea", "build", "node_modules", ".atlas"}
    for current, dirs, files in os.walk(root):
        rel = Path(current).relative_to(root)
        if len(rel.parts) > 6:
            dirs[:] = []
            continue
        dirs[:] = [name for name in dirs if name not in ignored]
        if "build.gradle" in files or "build.gradle.kts" in files or "settings.gradle.kts" in files:
            gradle = Path(current)
            manifest = next(iter(gradle.glob("src/main/AndroidManifest.xml")), None)
            package_id = None
            if manifest and manifest.is_file():
                match = re.search(r'package\s*=\s*["\']([^"\']+)', manifest.read_text("utf-8", errors="replace"))
                package_id = match.group(1) if match else None
            hits.append({"path": gradle.relative_to(root).as_posix() or ".",
                         "module": gradle.name, "applicationId": package_id,
                         "manifest": manifest.relative_to(root).as_posix() if manifest else None,
                         "apk_outputs": [p.relative_to(root).as_posix() for p in gradle.glob("build/outputs/apk/**/*.apk")]})
    return {"workspace": str(root), "projects": hits}


def _android_create(workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
    name = str(arguments.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError("name must be a valid Kotlin/Java identifier")
    package_name = str(arguments.get("packageName") or "com.example." + re.sub(r"[^A-Za-z0-9_]", "", name).lower())
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", package_name):
        raise ValueError("packageName must be a valid dotted Java package name")
    target = _workspace_path(workspace, str(arguments.get("dir") or name))
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)
    compile_sdk = 35
    min_sdk = int(arguments.get("minSdk") or 23)
    package_path = Path(*package_name.split("."))
    files = {
        "settings.gradle.kts": f'''pluginManagement {{ repositories {{ google(); mavenCentral(); gradlePluginPortal() }} }}\ndependencyResolutionManagement {{ repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories {{ google(); mavenCentral() }} }}\nrootProject.name = "{name}"\ninclude(":app")\n''',
        "build.gradle.kts": '''plugins { id("com.android.application") version "8.6.1" apply false; kotlin("android") version "2.0.21" apply false; id("org.jetbrains.kotlin.plugin.compose") version "2.0.21" apply false }\n''',
        "gradle.properties": "android.useAndroidX=true\nkotlin.code.style=official\norg.gradle.jvmargs=-Xmx2g -Dfile.encoding=UTF-8\n",
        "app/build.gradle.kts": f'''plugins {{ id("com.android.application"); kotlin("android"); id("org.jetbrains.kotlin.plugin.compose") }}\nandroid {{ namespace = "{package_name}"; compileSdk = {compile_sdk}; defaultConfig {{ applicationId = "{package_name}"; minSdk = {min_sdk}; targetSdk = {compile_sdk}; versionCode = 1; versionName = "1.0" }}; buildFeatures {{ compose = true }} }}\ndependencies {{ implementation(platform("androidx.compose:compose-bom:2024.09.03")); implementation("androidx.activity:activity-compose:1.9.2"); implementation("androidx.compose.material3:material3"); implementation("androidx.compose.ui:ui") }}\n''',
        "app/src/main/AndroidManifest.xml": f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:label="{name}" android:theme="@android:style/Theme.Material.Light.NoActionBar"><activity android:name=".{name}Activity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>\n''',
        f"app/src/main/java/{package_path}/{name}Activity.kt": f'''package {package_name}\n\nimport android.os.Bundle\nimport androidx.activity.ComponentActivity\nimport androidx.activity.compose.setContent\nimport androidx.compose.material3.MaterialTheme\nimport androidx.compose.material3.Text\n\nclass {name}Activity : ComponentActivity() {{ override fun onCreate(savedInstanceState: Bundle?) {{ super.onCreate(savedInstanceState); setContent {{ MaterialTheme {{ Text("{name}") }} }} }} }}\n''',
    }
    for rel, content in files.items():
        path = target / rel
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return {"created": True, "path": str(target), "applicationId": package_name,
            "files": list(files)}


def _android_build(workspace: str, arguments: dict[str, Any]) -> dict[str, Any]:
    project = _android_project(workspace, arguments)
    wrapper = project / ("gradlew.bat" if os.name == "nt" else "gradlew")
    gradle = str(wrapper) if wrapper.is_file() else _tool_path("gradle")
    if not gradle:
        raise RuntimeError("Gradle is unavailable and this project has no Gradle wrapper.")
    module = str(arguments.get("module") or "app").strip(":")
    variant = str(arguments.get("variant") or "debug")
    task = f":{module}:assemble{variant[:1].upper()}{variant[1:]}"
    timeout = _timeout_seconds(arguments, 600_000)
    output = _run_checked([gradle, task, "--console=plain"], cwd=project, timeout=timeout)
    candidates = sorted((project / module / "build/outputs/apk").glob(f"**/*{variant}*.apk"))
    if not candidates:
        candidates = sorted((project / module / "build/outputs/apk").glob("**/*.apk"))
    application_id = str(arguments.get("applicationId") or "")
    if not application_id:
        gradle_file = project / module / "build.gradle.kts"
        if gradle_file.is_file():
            match = re.search(r'applicationId\s*=\s*["\']([^"\']+)', gradle_file.read_text("utf-8", errors="replace"))
            application_id = match.group(1) if match else ""
    return {"built": True, "project": str(project), "task": task,
            "apk": str(candidates[-1]) if candidates else None,
            "applicationId": application_id, "output_tail": output[-5000:]}


def _android_start(arguments: dict[str, Any]) -> dict[str, Any]:
    emulator = _tool_path("emulator")
    if not emulator:
        raise RuntimeError("Android emulator executable is unavailable.")
    avd = str(arguments.get("avd") or "").strip()
    if not avd:
        avds = [line.strip() for line in _run_checked([emulator, "-list-avds"], timeout=15).splitlines()
                if line.strip()]
        if not avds:
            raise ValueError("No Android AVDs are installed. Create one with android_create_avd first.")
        avd = avds[0]
    devices = _android_devices(timeout=15)
    before = {item["serial"] for item in devices}
    for item in devices:
        serial = item["serial"]
        if item["state"] == "device" and serial.startswith("emulator-"):
            try:
                active_avd = _android_avd_name(serial)
            except (OSError, RuntimeError, subprocess.SubprocessError):
                continue
            if active_avd == avd:
                raise RuntimeError(f'Android AVD "{avd}" is already running as {serial}.')
    proc = subprocess.Popen([emulator, "-avd", avd], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                            start_new_session=(os.name != "nt"), shell=False)
    deadline = time.monotonic() + _timeout_seconds(arguments, 180_000)
    while time.monotonic() < deadline:
        try:
            for ready in _android_devices(timeout=10):
                serial = ready["serial"]
                if not (serial.startswith("emulator-") and ready["state"] == "device" and serial not in before):
                    continue
                try:
                    active_avd = _android_avd_name(serial)
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    continue
                if active_avd != avd:
                    continue
                try:
                    booted = str(_adb(serial, "shell", "getprop", "sys.boot_completed", timeout=5).stdout).strip() == "1"
                except (OSError, RuntimeError, subprocess.SubprocessError):
                    continue
                if booted:
                    return {"started": True, "avd": avd, "serial": serial, "pid": proc.pid}
        except (OSError, RuntimeError, subprocess.SubprocessError):
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"Android emulator exited before boot completed (exit {proc.returncode}).")
        time.sleep(1)
    raise TimeoutError(f'Android emulator "{avd}" did not finish booting before timeout (pid {proc.pid}).')


def _android_ui_xml(serial: str, *, timeout: float = 30) -> str:
    _adb(serial, "shell", "uiautomator", "dump", "/sdcard/window.xml", timeout=timeout)
    return str(_adb(serial, "shell", "cat", "/sdcard/window.xml", timeout=timeout).stdout)


def _android_ui_elements(xml: str) -> list[dict[str, Any]]:
    elements = []
    for match in re.finditer(r"<node\b([^>]*)/?>", xml):
        attrs = {key: value for key, value in re.findall(r'([\w-]+)="([^"]*)"', match.group(1))}
        bounds = re.search(r"\[(\d+),(\d+)]\[(\d+),(\d+)]", attrs.get("bounds", ""))
        item: dict[str, Any] = {
            "index": len(elements), "text": attrs.get("text") or None,
            "contentDescription": attrs.get("content-desc") or None,
            "resourceId": attrs.get("resource-id") or None,
            "className": attrs.get("class") or None,
            "clickable": attrs.get("clickable") == "true",
            "enabled": attrs.get("enabled") != "false",
        }
        if bounds:
            left, top, right, bottom = map(int, bounds.groups())
            item["bounds"] = {"left": left, "top": top, "right": right, "bottom": bottom,
                              "centerX": round((left + right) / 2), "centerY": round((top + bottom) / 2)}
        elements.append(item)
    return elements


def _android(name: str, args: dict[str, Any], workspace: str) -> dict[str, Any]:
    if name == "android_preflight":
        status = _android_sdk_status()
        status["devices"] = _android_devices() if status["tools"]["adb"] else []
        return status
    if name == "android_discover_project":
        return _android_discover(workspace)
    if name == "android_create_app":
        return _android_create(workspace, args)
    if name in {"android_build_app", "android_build_and_run"}:
        built = _android_build(workspace, args)
        if name == "android_build_app":
            return built
        if not built.get("apk") or not built.get("applicationId"):
            raise RuntimeError("Build succeeded but APK or applicationId could not be resolved.")
        serial = _android_serial(args)
        _adb(serial, "install", "-r", str(built["apk"]), timeout=_timeout_seconds(args, 120_000))
        activity = str(args.get("launchActivity") or built["applicationId"])
        if args.get("launchActivity"):
            app_id = str(built["applicationId"])
            component = activity if "/" in activity else f"{app_id}/{activity if activity.startswith('.') or activity.startswith(app_id + '.') else app_id + '.' + activity}"
            _adb(serial, "shell", "am", "start", "-n", component, timeout=_timeout_seconds(args, 60_000))
        else:
            _adb(serial, "shell", "monkey", "-p", str(built["applicationId"]), "-c",
                 "android.intent.category.LAUNCHER", "1", timeout=_timeout_seconds(args, 60_000))
        return {**built, "serial": serial, "launched": True, "activity_hint": activity}
    if name == "android_list_devices":
        return {"devices": _android_devices()}
    if name == "android_ui_status":
        adb = _tool_path("adb")
        return {"backend": "adb-uiautomator", "available": bool(adb),
                "reason": None if adb else "Install Android platform-tools to use UI Automator."}
    emulator = _tool_path("emulator")
    if name == "android_list_avds":
        if not emulator:
            return {"available": False, "avds": [], "reason": "Android emulator executable is unavailable."}
        return {"available": True, "avds": _run_checked([emulator, "-list-avds"], timeout=15).splitlines()}
    if name == "android_start_emulator":
        return _android_start(args)
    if name == "android_stop_emulator":
        serial = str(args["serial"])
        if not serial.startswith("emulator-"):
            raise ValueError("serial must refer to an emulator-* instance")
        _adb(serial, "emu", "kill", timeout=15)
        return {"stopped": True, "serial": serial}
    if name == "android_create_avd":
        avdmanager = _tool_path("avdmanager")
        if not avdmanager:
            raise RuntimeError("avdmanager is unavailable; install Android command-line tools.")
        avd_name = str(args.get("name") or "Atlas_API_35")
        package = str(args.get("packageId") or "system-images;android-35;google_apis;x86_64")
        command = [avdmanager, "create", "avd", "--name", avd_name, "--package", package]
        if args.get("device"):
            command.extend(["--device", str(args["device"])])
        if args.get("force"):
            command.append("--force")
        output = _run_checked(command, timeout=120)
        return {"created": True, "name": avd_name, "packageId": package, "output": output[-2000:]}
    if name in {"android_install_app", "android_launch_app", "android_terminate_app", "android_open_url",
                "android_screenshot", "android_logs", "android_ui_describe",
                "android_ui_resolve", "android_ui_tap", "android_ui_swipe", "android_ui_type_text", "android_ui_keyevent"}:
        serial = _android_serial(args)
        if name == "android_install_app":
            apk = _workspace_path(workspace, str(args["apkPath"]))
            if not apk.is_file() or apk.suffix.lower() != ".apk":
                raise ValueError("apkPath must point to an existing .apk file inside the workspace")
            _adb(serial, "install", "-r", str(apk), timeout=_timeout_seconds(args, 120_000))
            return {"installed": True, "serial": serial, "apkPath": str(apk)}
        if name == "android_launch_app":
            app_id = str(args["applicationId"])
            if args.get("activity"):
                activity = str(args["activity"])
                component = activity if "/" in activity else f"{app_id}/{activity if activity.startswith('.') or activity.startswith(app_id + '.') else app_id + '.' + activity}"
                _adb(serial, "shell", "am", "start", "-W", "-n", component,
                     timeout=_timeout_seconds(args, 60_000))
            else:
                _adb(serial, "shell", "monkey", "-p", app_id, "-c", "android.intent.category.LAUNCHER", "1",
                     timeout=_timeout_seconds(args, 60_000))
            return {"launched": True, "serial": serial, "applicationId": app_id}
        if name == "android_terminate_app":
            _adb(serial, "shell", "am", "force-stop", str(args["applicationId"]),
                 timeout=_timeout_seconds(args, 30_000))
            return {"terminated": True, "serial": serial}
        if name == "android_open_url":
            parsed = urllib.parse.urlparse(str(args["url"]))
            if not parsed.scheme:
                raise ValueError("url must include a scheme")
            url = str(args["url"])
            if len(url) > 2048:
                raise ValueError("url is too long")
            _adb(serial, "shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url,
                 timeout=_timeout_seconds(args, 30_000))
            return {"opened": True, "serial": serial, "url": args["url"]}
        if name == "android_screenshot":
            output = _workspace_path(workspace, str(args.get("path") or f".atlas/mobile/android/{serial}-{uuid.uuid4().hex[:8]}.png"))
            output.parent.mkdir(parents=True, exist_ok=True)
            image = _adb(serial, "exec-out", "screencap", "-p", binary=True,
                         timeout=_timeout_seconds(args, 30_000)).stdout
            output.write_bytes(image)
            return _screenshot_result(output, device_key="serial", device_id=serial)
        if name == "android_logs":
            lines = max(1, min(5000, int(args.get("lines") or 500)))
            app_id = str(args.get("applicationId") or "")
            command = ["logcat", "-d", "-t", str(lines)]
            if app_id:
                pid = str(_adb(serial, "shell", "pidof", app_id,
                               timeout=_timeout_seconds(args, 10_000)).stdout).strip().split()
                if not pid:
                    return {"serial": serial, "applicationId": app_id, "lines": []}
                command.extend(["--pid", pid[0]])
            output = str(_adb(serial, *command, timeout=_timeout_seconds(args, 30_000)).stdout)
            limit = max(1, min(5000, int(args.get("limit") or lines)))
            return {"serial": serial, "applicationId": app_id or None,
                    "lines": output.splitlines()[-limit:]}
        if name in {"android_ui_describe", "android_ui_resolve"}:
            elements = _android_ui_elements(_android_ui_xml(serial, timeout=_timeout_seconds(args, 30_000)))
            if name == "android_ui_describe":
                return {"serial": serial, "elements": elements[:500]}
            query = str(args["query"]).strip().casefold()
            hits = [item for item in elements if query in " ".join(str(item.get(k) or "") for k in
                    ("text", "contentDescription", "resourceId", "className")).casefold()]
            if not hits:
                raise ValueError(f"No visible Android UI element matched: {args['query']}")
            return {"serial": serial, "matches": hits[:25]}
        if name == "android_ui_tap":
            _adb(serial, "shell", "input", "tap", str(round(float(args["x"]))), str(round(float(args["y"]))),
                 timeout=_timeout_seconds(args, 30_000))
            return {"tapped": True, "serial": serial, "x": args["x"], "y": args["y"]}
        if name == "android_ui_swipe":
            command = ["shell", "input", "swipe", *(str(round(float(args[key]))) for key in ("x1", "y1", "x2", "y2")),
                       str(max(1, int(args.get("durationMs") or 300)))]
            _adb(serial, *command, timeout=_timeout_seconds(args, 30_000))
            return {"swiped": True, "serial": serial}
        if name == "android_ui_type_text":
            value = str(args["text"])
            if len(value) > 1000:
                raise ValueError("text input is limited to 1000 characters")
            value = value.replace("%", "%25").replace(" ", "%s").replace("\t", "%s")
            _adb(serial, "shell", "input", "text", value, timeout=_timeout_seconds(args, 30_000))
            return {"typed": True, "serial": serial, "length": len(str(args["text"]))}
        if name == "android_ui_keyevent":
            key = str(args["key"]).upper()
            aliases = {"BACK": "KEYCODE_BACK", "HOME": "KEYCODE_HOME", "ENTER": "KEYCODE_ENTER",
                       "APP_SWITCH": "KEYCODE_APP_SWITCH", "MENU": "KEYCODE_MENU", "SEARCH": "KEYCODE_SEARCH"}
            value = aliases.get(key)
            if value is None:
                raise ValueError("Unsupported Android key event")
            _adb(serial, "shell", "input", "keyevent", value, timeout=_timeout_seconds(args, 30_000))
            return {"pressed": True, "serial": serial, "key": key}
    raise ValueError(f"Unknown Android tool: {name}")


def _require_ios() -> str:
    if platform.system() != "Darwin":
        raise RuntimeError("iOS Simulator tools require macOS and Xcode.")
    xcrun = shutil.which("xcrun")
    if not xcrun:
        raise RuntimeError("xcrun is unavailable; install Xcode command-line tools.")
    return xcrun


def _simulators() -> list[dict[str, Any]]:
    xcrun = _require_ios()
    result = _result([xcrun, "simctl", "list", "devices", "available", "-j"], timeout=30)
    if result.returncode:
        raise RuntimeError(str(result.stderr or "simctl failed"))
    data = json.loads(result.stdout)
    rows = []
    for runtime, devices in data.get("devices", {}).items():
        if not re.search(r"(?:^|[.\s-])(?:iOS|iPadOS)(?:$|[.\s-])", runtime, re.IGNORECASE):
            continue
        for device in devices:
            rows.append({**device, "runtime": runtime})
    return rows


def _ios_udid(args: dict[str, Any]) -> str:
    devices = _simulators()
    requested = str(args.get("udid") or "")
    if requested:
        if not any(item.get("udid") == requested for item in devices):
            raise ValueError(f"iOS simulator not found: {requested}")
        return requested
    name = str(args.get("device") or "").casefold()
    runtime = str(args.get("runtime") or "").casefold()
    matches = [item for item in devices
               if (not name or name in str(item.get("name", "")).casefold())
               and (not runtime or runtime in str(item.get("runtime", "")).casefold())]
    if not matches:
        raise RuntimeError("No matching iOS simulator is available.")
    booted = next((item for item in matches if item.get("state") == "Booted"), None)
    if booted and not name and not runtime:
        return str(booted["udid"])
    preferred = next((item for item in matches if str(item.get("name", "")).startswith("iPhone")), None)
    return str((booted or preferred or matches[0])["udid"])


def _ios_boot_target(args: dict[str, Any], *, open_simulator: bool = False) -> dict[str, Any]:
    xcrun = _require_ios()
    udid = _ios_udid(args)
    selected = next(item for item in _simulators() if item.get("udid") == udid)
    if selected.get("state") != "Booted":
        try:
            _run_checked([xcrun, "simctl", "boot", udid], timeout=60)
        except RuntimeError:
            refreshed = next((item for item in _simulators() if item.get("udid") == udid), None)
            if not refreshed or refreshed.get("state") != "Booted":
                raise
        _run_checked([xcrun, "simctl", "bootstatus", udid, "-b"], timeout=120)
    if open_simulator:
        _run_checked(["open", "-a", "Simulator", "--args", "-CurrentDeviceUDID", udid], timeout=30)
    selected = next((item for item in _simulators() if item.get("udid") == udid), selected)
    return {"udid": udid, "device": selected.get("name"), "runtime": selected.get("runtime")}


def _ios_project(workspace: str, args: dict[str, Any]) -> tuple[Path, str]:
    root = _workspace_path(workspace)
    project = args.get("project")
    xcode_workspace = args.get("workspace")
    if project:
        path = _workspace_path(workspace, str(project))
        if path.suffix != ".xcodeproj" or not path.exists():
            raise ValueError("project must be an existing .xcodeproj path inside the workspace")
        return path, "project"
    if xcode_workspace:
        path = _workspace_path(workspace, str(xcode_workspace))
        if path.suffix != ".xcworkspace" or not path.exists():
            raise ValueError("workspace must be an existing .xcworkspace path inside the workspace")
        return path, "workspace"
    candidate = next(iter(root.glob("*.xcworkspace")), None)
    kind = "workspace"
    if candidate is None:
        candidate = next(iter(root.glob("*.xcodeproj")), None)
        kind = "project"
    if candidate is None:
        candidate = next(iter(root.rglob("*.xcworkspace")), None)
        kind = "workspace"
    if candidate is None:
        candidate = next(iter(root.rglob("*.xcodeproj")), None)
        kind = "project"
    if candidate is None:
        raise FileNotFoundError("No .xcodeproj or .xcworkspace was found in the workspace.")
    return candidate, kind


def _ios_schemes(path: Path, kind: str) -> list[str]:
    xcrun = _require_ios()
    flag = "-workspace" if kind == "workspace" else "-project"
    result = _result([xcrun, "xcodebuild", "-list", "-json", flag, str(path)], timeout=60)
    if result.returncode:
        return []
    try:
        data = json.loads(result.stdout)
        section = data.get("workspace") or data.get("project") or {}
        return [str(item) for item in section.get("schemes", [])]
    except (ValueError, TypeError):
        return []


def _ios_build(workspace: str, args: dict[str, Any], *, open_simulator: bool = False) -> dict[str, Any]:
    xcrun = _require_ios()
    path, kind = _ios_project(workspace, args)
    schemes = _ios_schemes(path, kind)
    scheme = str(args.get("scheme") or (schemes[0] if schemes else path.stem))
    simulator = str(_ios_boot_target(args, open_simulator=open_simulator)["udid"])
    root = Path(workspace).resolve()
    derived = _workspace_path(workspace, str(args.get("derivedDataPath") or ".atlas/ios-derived"))
    derived.mkdir(parents=True, exist_ok=True)
    command = [xcrun, "xcodebuild", "-scheme", scheme,
               "-configuration", str(args.get("configuration") or "Debug"),
               "-destination", f"platform=iOS Simulator,id={simulator}", "-derivedDataPath", str(derived),
               "-sdk", "iphonesimulator", "CODE_SIGNING_ALLOWED=NO", "build"]
    command.extend(["-workspace" if kind == "workspace" else "-project", str(path)])
    timeout = float(args.get("timeoutMs") or 600000) / 1000
    output = _run_checked(command, cwd=root, timeout=timeout, max_chars=30000)
    apps = sorted(derived.glob(f"Build/Products/*-iphonesimulator/{scheme}.app"))
    if not apps:
        apps = sorted(derived.glob("Build/Products/*-iphonesimulator/*.app"))
    bundle_id = str(args.get("bundleId") or "")
    if not bundle_id and apps:
        try:
            with (apps[-1] / "Info.plist").open("rb") as stream:
                bundle_id = str(plistlib.load(stream).get("CFBundleIdentifier") or "")
        except (OSError, plistlib.InvalidFileException, AttributeError):
            bundle_id = ""
    return {"built": True, "project": str(path), "scheme": scheme,
            "simulator": simulator, "appPath": str(apps[-1]) if apps else None,
            "bundleId": bundle_id, "derivedDataPath": str(derived),
            "output_tail": output[-5000:]}


def _ios_create(workspace: str, args: dict[str, Any]) -> dict[str, Any]:
    xcodegen = shutil.which("xcodegen")
    if not xcodegen:
        raise RuntimeError("XcodeGen is required for ios_create_app. Install it with Homebrew (`brew install xcodegen`).")
    name = str(args.get("name") or "").strip()
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError("name must be a valid Swift type identifier")
    bundle_id = str(args.get("bundleId") or f"com.example.{re.sub(r'[^A-Za-z0-9]', '', name).lower()}")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+", bundle_id):
        raise ValueError("bundleId must be a dotted reverse-DNS identifier")
    deployment = str(args.get("deployment") or "17.0")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", deployment):
        raise ValueError("deployment must be a numeric iOS version such as 16.0")
    target = _workspace_path(workspace, str(args.get("dir") or name))
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory is not empty: {target}")
    source = target / "Sources" / name
    source.mkdir(parents=True, exist_ok=True)
    (source / "ContentView.swift").write_text(
        "import SwiftUI\n\nstruct ContentView: View { var body: some View { Text(\"" + name + "\").padding() } }\n",
        encoding="utf-8")
    (source / f"{name}App.swift").write_text(
        "import SwiftUI\n\n@main struct " + name + "App: App { var body: some Scene { WindowGroup { ContentView() } } }\n",
        encoding="utf-8")
    (target / "project.yml").write_text(
        f"name: {json.dumps(name)}\noptions:\n  bundleIdPrefix: {json.dumps('.'.join(bundle_id.split('.')[:-1]))}\n\ntargets:\n  {json.dumps(name)}:\n    type: application\n    platform: iOS\n    deploymentTarget: {json.dumps(deployment)}\n    sources: [Sources/{name}]\n    settings:\n      PRODUCT_BUNDLE_IDENTIFIER: {json.dumps(bundle_id)}\n      INFOPLIST_KEY_UIApplicationSceneManifest_Generation: YES\n      INFOPLIST_KEY_UILaunchScreen_Generation: YES\n      SWIFT_VERSION: 5.0\n",
        encoding="utf-8")
    _run_checked([xcodegen, "generate", "--spec", "project.yml"], cwd=target, timeout=60)
    return {"created": True, "path": str(target), "bundleId": bundle_id,
            "project": str(target / f"{name}.xcodeproj")}


def _ios(name: str, args: dict[str, Any], workspace: str) -> dict[str, Any]:
    if name == "ios_preflight":
        if platform.system() != "Darwin":
            return {"platform": platform.system(), "available": False,
                    "reason": "iOS Simulator tools require macOS and Xcode."}
        xcrun = shutil.which("xcrun")
        xcodebuild = shutil.which("xcodebuild")
        simulators = []
        reason = None
        if xcrun and xcodebuild:
            try:
                simulators = _simulators()
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
                reason = str(exc)
        else:
            reason = "Install full Xcode with xcrun and xcodebuild to use iOS Simulator tools."
        return {"platform": platform.system(), "xcrun": xcrun, "xcodebuild": xcodebuild,
                "xcodegen": shutil.which("xcodegen"), "idb": shutil.which("idb"),
                "simulators": len(simulators), "available": bool(xcrun and xcodebuild and simulators),
                "reason": reason}
    xcrun = _require_ios()
    if name == "ios_list_simulators":
        return {"simulators": _simulators()}
    if name == "ios_discover_project":
        root = Path(workspace).resolve()
        projects = []
        for ext in ("*.xcodeproj", "*.xcworkspace"):
            for path in root.rglob(ext):
                if any(part in {".git", "node_modules", ".atlas", "DerivedData"} for part in path.parts):
                    continue
                kind = "workspace" if path.suffix == ".xcworkspace" else "project"
                projects.append({"path": path.relative_to(root).as_posix(), "kind": kind,
                                 "schemes": _ios_schemes(path, kind)})
        return {"projects": projects}
    if name == "ios_create_app":
        return _ios_create(workspace, args)
    if name in {"ios_build_app", "ios_build_and_run"}:
        open_simulator = bool(args.get("openSimulator", name == "ios_build_and_run"))
        built = _ios_build(workspace, args, open_simulator=open_simulator)
        if name == "ios_build_app":
            return built
        if not built.get("appPath"):
            raise RuntimeError("Build succeeded but no .app bundle was found.")
        udid = str(built["simulator"])
        _run_checked([xcrun, "simctl", "install", udid, str(built["appPath"])], timeout=120)
        bundle_id = str(args.get("bundleId") or built.get("bundleId") or "")
        if not bundle_id:
            raise ValueError("bundleId is required when it cannot be resolved from build settings")
        command = [xcrun, "simctl", "launch", udid, bundle_id]
        command.extend(str(item) for item in (args.get("launchArgs") or []))
        _run_checked(command, timeout=30)
        return {**built, "installed": True, "launched": True, "bundleId": bundle_id}
    if name == "ios_show_simulator":
        udid = str(args.get("udid") or "")
        command = ["open", "-a", "Simulator"]
        if udid:
            command.extend(["--args", "-CurrentDeviceUDID", udid])
        _run_checked(command, timeout=30)
        return {"opened": True, "udid": udid or None}
    if name == "ios_boot_simulator":
        target = _ios_boot_target(args, open_simulator=bool(args.get("openSimulator", True)))
        return {"booted": True, **target}
    if name == "ios_ui_status":
        idb = shutil.which("idb")
        return {"backend": "idb", "available": bool(idb),
                "reason": None if idb else "Install Facebook idb to use iOS UI actions."}
    if name in {"ios_install_app", "ios_launch_app", "ios_terminate_app", "ios_open_url", "ios_screenshot",
                "ios_logs", "ios_ui_tap", "ios_ui_swipe", "ios_ui_type_text", "ios_ui_button", "ios_ui_describe"}:
        if name == "ios_logs":
            udid = _ios_udid(args)
        else:
            should_open = name in {"ios_launch_app", "ios_open_url"} or (
                name == "ios_screenshot" and bool(args.get("openSimulator")))
            udid = str(_ios_boot_target(args, open_simulator=should_open)["udid"])
        if name == "ios_install_app":
            app_path = _workspace_path(workspace, str(args["appPath"]))
            if not app_path.is_dir() or app_path.suffix != ".app":
                raise ValueError("appPath must point to an existing .app bundle inside the workspace")
            _run_checked([xcrun, "simctl", "install", udid, str(app_path)], timeout=120)
            return {"installed": True, "udid": udid, "appPath": str(app_path)}
        if name == "ios_launch_app":
            command = [xcrun, "simctl", "launch", udid, str(args["bundleId"])]
            command.extend(str(item) for item in (args.get("launchArgs") or []))
            return {"launched": True, "udid": udid, "output": _run_checked(command, timeout=30)}
        if name == "ios_terminate_app":
            _run_checked([xcrun, "simctl", "terminate", udid, str(args["bundleId"])], timeout=30)
            return {"terminated": True, "udid": udid}
        if name == "ios_open_url":
            if not urllib.parse.urlparse(str(args["url"])).scheme:
                raise ValueError("url must include a scheme")
            _run_checked([xcrun, "simctl", "openurl", udid, str(args["url"])], timeout=30)
            return {"opened": True, "udid": udid, "url": args["url"]}
        if name == "ios_screenshot":
            output = _workspace_path(workspace, str(args.get("path") or f".atlas/mobile/ios/{udid}-{uuid.uuid4().hex[:8]}.png"))
            output.parent.mkdir(parents=True, exist_ok=True)
            _run_checked([xcrun, "simctl", "io", udid, "screenshot", str(output)], timeout=30)
            return _screenshot_result(output, device_key="udid", device_id=udid)
        if name == "ios_logs":
            seconds = max(1, min(3600, int(args.get("seconds") or 180)))
            limit = max(1, min(5000, int(args.get("limit") or 500)))
            command = [xcrun, "simctl", "spawn", udid, "log", "show", "--last",
                       f"{seconds}s", "--style", "compact"]
            bundle_id = str(args.get("bundleId") or "")
            if bundle_id:
                if not re.fullmatch(r"[A-Za-z0-9_.-]+", bundle_id):
                    raise ValueError("bundleId must contain only letters, digits, dots, underscores or hyphens")
                process = bundle_id.split(".")[-1]
                command.extend(["--predicate", f'subsystem CONTAINS "{bundle_id}" OR process CONTAINS "{process}"'])
            output = _run_checked(command, timeout=45)
            return {"udid": udid, "bundleId": bundle_id or None,
                    "lines": output.splitlines()[-limit:]}
        idb = shutil.which("idb")
        if not idb:
            raise RuntimeError("iOS UI automation requires idb; other simulator tools remain available.")
        if name == "ios_ui_describe":
            output = _run_checked([idb, "ui", "describe-all", "--json", "--udid", udid], timeout=30)
            return {"udid": udid, "description": output[-12000:]}
        if name == "ios_ui_tap":
            command = [idb, "ui", "tap", str(args["x"]), str(args["y"])]
            if args.get("duration") is not None:
                command.extend(["--duration", str(args["duration"])])
            command.extend(["--udid", udid])
            _run_checked(command, timeout=60)
            return {"tapped": True, "udid": udid, "x": args["x"], "y": args["y"]}
        if name == "ios_ui_swipe":
            command = [idb, "ui", "swipe", str(args["x1"]), str(args["y1"]),
                       str(args["x2"]), str(args["y2"])]
            if args.get("delta") is not None:
                command.extend(["--delta", str(args["delta"])])
            command.extend(["--udid", udid])
            _run_checked(command, timeout=60)
            return {"swiped": True, "udid": udid}
        if name == "ios_ui_type_text":
            value = str(args["text"])
            if len(value) > 1000:
                raise ValueError("text input is limited to 1000 characters")
            _run_checked([idb, "ui", "text", value, "--udid", udid], timeout=60)
            return {"typed": True, "udid": udid, "length": len(value)}
        if name == "ios_ui_button":
            command = [idb, "ui", "button", str(args["button"]).upper()]
            if args.get("duration") is not None:
                command.extend(["--duration", str(args["duration"])])
            command.extend(["--udid", udid])
            _run_checked(command, timeout=60)
            return {"pressed": True, "udid": udid, "button": args["button"]}
    raise ValueError(f"Unknown iOS tool: {name}")


def _call_mobile_tool(name: str, args: dict[str, Any], workspace: str) -> dict[str, Any]:
    if name.startswith("android_"):
        if sys.platform not in {"darwin", "win32"}:
            raise RuntimeError("ZCode Android emulator tools are available on Windows and macOS only.")
        return _android(name, args, workspace)
    if name.startswith("ios_"):
        if sys.platform != "darwin":
            raise RuntimeError("ZCode iOS simulator tools are available on macOS only.")
        return _ios(name, args, workspace)
    raise ValueError(f"Unknown mobile tool: {name}")
