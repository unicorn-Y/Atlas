"""UMHarness: real dual-service test harness for the unified-memory waves.

Spawns one real Atlas backend (``uvicorn atlas.server:app``) and one real
MemoryOS service (``uvicorn app:app``) as subprocesses in their own
interpreters, each bound to a fresh isolated data root under
``artifacts/unified-memory/test-runtime/<uuid>/``. Only the LLM provider is
fake: :class:`~tests.fakes.fake_llm_provider.FakeLLMServer` runs loopback-only
inside the pytest process and every chat/tool/memory path under test goes
through the real services (T00.2, UM00).

Isolation rules (00_master_task.md §8):
    - ``ATLAS_DATA_DIR`` points at this instance's ``atlas/`` directory.
    - ``MEMORYOS_DATA_ROOT`` / ``MEMORYOS_DB_PATH`` point at this instance's
      ``memoryos/`` directory.
    - Every MemoryOS event class used by tests is ``TEST``.
    - Never touches production paths (``D:/Atlas/data``, ``D:/MemoryOSData``)
      or production ports; the harness refuses to start when the process env
      already pins a production data root.

Bootstrap precedent: ``core/tests/fakes/k1_harness.py`` (isolated backend +
scripted fake provider) and ``IsolatedBackend`` in
``core/tests/test_c1_websocket_acceptance.py``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from tests.fakes.fake_llm_provider import (
    MODEL_ID,
    FakeLLMServer,
    Text,
    ToolCall,
    write_hermes_home,
)
from atlas.memory.unified_client import observation_content_hash

ATLAS_REPO = Path(__file__).resolve().parents[3]          # D:/Atlas
CORE_DIR = ATLAS_REPO / "core"
MEMORYOS_REPO = Path(
    os.environ.get("UM_MEMORYOS_REPO", str(ATLAS_REPO.parent / "MemoryOS"))
)                                                          # D:/MemoryOS

FIXTURES_DIR = ATLAS_REPO / "tests" / "fixtures" / "unified_memory"
SEEDS_DIR = FIXTURES_DIR / "seeds"
ARTIFACTS_BASE = ATLAS_REPO / "artifacts" / "unified-memory" / "test-runtime"

# Production paths the harness must never touch (00_master_task.md §8).
PRODUCTION_ATLAS_DATA = ATLAS_REPO / "data"
PRODUCTION_MEMORYOS_ROOT = Path(r"D:\MemoryOSData")

# Test-runtime identity constants (T00.2).
TEST_INTERNAL_TOKEN = "test-internal-token"
TEST_OWNER_TOKEN = "test-owner-token"
ATLAS_API_TOKEN = "um-test-atlas-token"
FAKE_API_KEY = "sk-fake-e2e"
EVENT_CLASS = "TEST"
HEALTH_TIMEOUT_S = 60.0
STOP_TIMEOUT_S = 5.0

TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}

#: Aspects whose isolation / deletion / side-effect scenarios are critical
#: (05_acceptance_matrix.md §3, mirrored in gen_manifest.py).
CRITICAL_ASPECTS = {"M03", "L03", "L04", "G02", "I03", "N01", "N02"}

_SCENARIO_LETTERS = {
    "a": "normal",
    "b": "confusable",
    "c": "edit_withdraw",
    "d": "restart_late_concurrent",
    "e": "entry_application",
}


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    """Drop inherited credentials/proxies so only explicit test values remain."""
    markers = ("API_KEY", "ACCESS_KEY", "SECRET", "TOKEN", "PASSWORD", "PASSWD",
               "CREDENTIAL", "AUTH")
    for key in list(env):
        upper = key.upper()
        if (any(marker in upper for marker in markers)
                or upper.startswith("HERMES_SESSION_")
                or upper.endswith("_PROXY")):
            env.pop(key, None)
    return env


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return "<log unavailable>"


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class UMHarness:
    """One isolated Atlas + MemoryOS pair. See module docstring for scope."""

    def __init__(self, *, artifacts_base: Path | None = None) -> None:
        self.artifacts_base = Path(artifacts_base) if artifacts_base else ARTIFACTS_BASE
        self.started = False
        self.stopped = False
        self._fake: FakeLLMServer | None = None
        self._atlas_proc: subprocess.Popen[bytes] | None = None
        self._memoryos_proc: subprocess.Popen[bytes] | None = None
        self._atlas_log_handle = None
        self._memoryos_log_handle = None
        self._logs_kept: dict[str, Path] = {}
        self._faults: dict[str, dict[str, Any]] = {}
        self._restarts: list[dict[str, Any]] = []
        self.runtime_manifest: dict[str, Any] = {
            "event_class": EVENT_CLASS,
            "faults": self._faults,
            "restarts": self._restarts,
        }

    # ------------------------------------------------------------------ paths

    @property
    def root(self) -> Path:
        return Path(self.runtime_manifest["runtime_root"])

    @property
    def atlas_data(self) -> Path:
        return Path(self.runtime_manifest["atlas_data"])

    @property
    def memoryos_data(self) -> Path:
        return Path(self.runtime_manifest["memoryos_data"])

    @property
    def workspace(self) -> Path:
        return Path(self.runtime_manifest["workspace"])

    @property
    def atlas_url(self) -> str:
        return f"http://127.0.0.1:{self.runtime_manifest['atlas_port']}"

    @property
    def memoryos_url(self) -> str:
        return f"http://127.0.0.1:{self.runtime_manifest['memoryos_port']}"

    # ------------------------------------------------------------------ start

    def start(self) -> "UMHarness":
        if self.started:
            raise RuntimeError("UMHarness.start() called twice")
        self._refuse_production_env()
        self.artifacts_base.mkdir(parents=True, exist_ok=True)
        runtime_root = self.artifacts_base / uuid.uuid4().hex
        atlas_data = runtime_root / "atlas"
        memoryos_data = runtime_root / "memoryos"
        workspace = runtime_root / "workspace"
        for directory in (atlas_data, memoryos_data, workspace,
                          runtime_root / "home", runtime_root / "logs",
                          runtime_root / "cwd-atlas", runtime_root / "cwd-memoryos"):
            directory.mkdir(parents=True)

        self.runtime_manifest.update({
            "runtime_root": str(runtime_root),
            "atlas_data": str(atlas_data),
            "memoryos_data": str(memoryos_data),
            "memoryos_db": str(memoryos_data / "db" / "memoryos.sqlite3"),
            "workspace": str(workspace),
            "authority_id": f"um-test-{uuid.uuid4().hex[:12]}",
            "started_at": datetime.now(UTC).isoformat(),
            "model": None,
            "atlas_port": None,
            "memoryos_port": None,
        })

        # 1. Fake model provider: loopback HTTP inside the pytest process.
        self._fake = FakeLLMServer(default_text="um-fake-ok")
        self._fake.start()
        self.runtime_manifest["model"] = {
            "provider": "fake-loopback",
            "base_url": self._fake.base_url,
            "model_id": MODEL_ID,
            "note": "FakeLLMServer 只替代模型供应商；记忆/会话/任务/调度/工具派发均为真实实现",
        }

        # 3. Ports first: the T01.3 unified-memory composition must point the
        #    Atlas config at THIS instance's MemoryOS port before the process
        #    starts (config values are read at import time of atlas.server).
        atlas_port, memoryos_port = _free_port(), _free_port()
        self.runtime_manifest["atlas_port"] = atlas_port
        self.runtime_manifest["memoryos_port"] = memoryos_port
        self.runtime_manifest["unified_memory"] = {
            "enabled": True,
            "service_url": f"http://127.0.0.1:{memoryos_port}",
            "proxy_prefix": "/api/unified-memory",
            "subject_binding": "atlas-fixture",
            "config_site": "atlas.toml [memory.unified] (T01.3 全入口组成)",
        }

        # 2. Atlas config + redirected Hermes home pointing at the fake provider.
        self._write_atlas_toml(atlas_data, memoryos_port)
        write_hermes_home(
            atlas_data / "engine", self._fake.base_url, api_key=FAKE_API_KEY,
            extra_config=(
                "tools:\n  tool_search:\n    enabled: off\n"
                "auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n"
            ),
        )

        # 4. Spawn both real services.
        self._atlas_log_handle = (runtime_root / "logs" / "atlas.log").open("wb")
        self._memoryos_log_handle = (runtime_root / "logs" / "memoryos.log").open("wb")
        self._atlas_proc = subprocess.Popen(
            self._atlas_command(atlas_port), cwd=str(runtime_root / "cwd-atlas"),
            env=self._atlas_env(atlas_data), stdout=self._atlas_log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._memoryos_proc = subprocess.Popen(
            self._memoryos_command(memoryos_port), cwd=str(runtime_root / "cwd-memoryos"),
            env=self._memoryos_env(memoryos_data), stdout=self._memoryos_log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.runtime_manifest["atlas_pid"] = self._atlas_proc.pid
        self.runtime_manifest["memoryos_pid"] = self._memoryos_proc.pid

        # 4. Wait for real health endpoints.
        self._wait_health("atlas", "/api/health", atlas_port,
                          runtime_root / "logs" / "atlas.log")
        self._wait_health("memoryos", "/v1/health", memoryos_port,
                          runtime_root / "logs" / "memoryos.log")
        self.runtime_manifest["healthy"] = True
        self.started = True
        self._write_manifest_snapshot()
        return self

    def _refuse_production_env(self) -> None:
        """Reject launches pinned to production data roots (T00.1 test-path rule)."""
        for var, production in (
            ("ATLAS_DATA_DIR", PRODUCTION_ATLAS_DATA),
            ("MEMORYOS_DATA_ROOT", PRODUCTION_MEMORYOS_ROOT),
            ("MEMORYOS_DB_PATH", PRODUCTION_MEMORYOS_ROOT),
        ):
            value = os.environ.get(var)
            if value and Path(value).resolve() == production.resolve():
                raise RuntimeError(
                    f"{var}={value} 指向生产数据根 {production}；"
                    "unified-memory 测试禁止使用生产数据"
                )

    def _atlas_command(self, port: int) -> list[str]:
        python = CORE_DIR / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            python = Path(sys.executable)
        return [str(python), "-m", "uvicorn", "atlas.server:app",
                "--host", "127.0.0.1", "--port", str(port)]

    def _memoryos_command(self, port: int) -> list[str]:
        python = MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"
        if not python.exists():
            raise RuntimeError(f"MemoryOS service venv 不存在: {python}")
        return [str(python), "-m", "uvicorn", "app:app",
                "--host", "127.0.0.1", "--port", str(port)]

    def _write_atlas_toml(self, atlas_data: Path, memoryos_port: int) -> None:
        """Minimal atlas.toml mirroring core/tests/conftest.py:11-31 + fake model.

        T01.3: ``[memory.unified]`` wires the spawned Atlas to THIS instance's
        MemoryOS (service_url + internal token live in the TOML because the
        harness scrubs *TOKEN* env vars from the child process env).
        """
        config_dir = atlas_data / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        assert self._fake is not None
        (config_dir / "atlas.toml").write_text(
            '[models]\ndefault="fake-model"\n'
            f'[models.gateway]\nbase_url="{self._fake.base_url}"\napi_key="{FAKE_API_KEY}"\n'
            '[[models.custom]]\nid="fake-model"\nname="UM fake fixture"\n'
            'provider="openai"\nlitellm_model="openai/fake-model"\nmax_output_tokens=512\n'
            '[agent]\nengine="hermes"\nverify_before_stop=false\n'
            '[tools]\nauto_start=[]\n[tools.servers]\n'
            '[scheduler]\nenabled=false\n'
            '[memory.unified]\nenabled=true\n'
            f'service_url="http://127.0.0.1:{memoryos_port}"\n'
            f'internal_token="{TEST_INTERNAL_TOKEN}"\n'
            'subject_binding="atlas-fixture"\n'
            'timeout_seconds=10.0\n',
            encoding="utf-8",
        )

    def _home_env(self, env: dict[str, str], runtime_root: Path) -> None:
        for key, folder in (("HOME", "home"), ("USERPROFILE", "home"),
                            ("APPDATA", "home/appdata"), ("LOCALAPPDATA", "home/localappdata"),
                            ("TEMP", "home/temp"), ("TMP", "home/temp")):
            directory = runtime_root / folder
            directory.mkdir(parents=True, exist_ok=True)
            env[key] = str(directory)

    def _atlas_env(self, atlas_data: Path) -> dict[str, str]:
        assert self._fake is not None
        env = _scrub_env(dict(os.environ))
        self._home_env(env, Path(self.runtime_manifest["runtime_root"]))
        env.update({
            "ATLAS_DATA_DIR": str(atlas_data),
            "HERMES_HOME": str(atlas_data / "engine"),
            "ATLAS_SCHEDULER_ENABLED": "false",
            "ATLAS_API_TOKEN": ATLAS_API_TOKEN,
            "ATLAS_API_KEY": FAKE_API_KEY,
            "ATLAS_API_BASE": self._fake.base_url,
            "OPENAI_API_BASE": self._fake.base_url,
            "OPENAI_BASE_URL": self._fake.base_url,
            "OPENAI_API_KEY": FAKE_API_KEY,
            "NO_PROXY": "127.0.0.1,localhost",
            "HERMES_TEST_MODE": "1",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(CORE_DIR),
        })
        env.pop("HERMES_SCRATCH_DIR", None)
        return env

    def _memoryos_env(self, memoryos_data: Path) -> dict[str, str]:
        env = _scrub_env(dict(os.environ))
        self._home_env(env, Path(self.runtime_manifest["runtime_root"]))
        env.update({
            "MEMORYOS_DATA_ROOT": str(memoryos_data),
            "MEMORYOS_DB_PATH": str(memoryos_data / "db" / "memoryos.sqlite3"),
            "MEMORYOS_INTERNAL_TOKEN": TEST_INTERNAL_TOKEN,
            "MEMORYOS_OWNER_TOKEN": TEST_OWNER_TOKEN,
            "MEMORYOS_EXTRACTOR_MODEL_REGISTRY_ID": "um-extractor-registry",
            "MEMORYOS_EXTRACTOR_MODEL_ID": "model-um-extractor",
            # T01.2 绑定修复：服务绑定主体 = 缺省 TEST context 的主体
            # （harness.default_context 的 atlas-fixture），T01.1 期间二者错位导致
            # h.api 注入的统一上下文被 403。T01.1 契约测试仍以 db 默认主体
            # （subject-default）通信，经显式兼容别名保持可用；其他主体仍 403。
            "MEMORYOS_MEMORY_SUBJECT_ID": "atlas-fixture",
            "MEMORYOS_MEMORY_SUBJECT_ALIASES": "subject-default",
            "NO_PROXY": "127.0.0.1,localhost",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(MEMORYOS_REPO / "service"),
        })
        return env

    def _wait_health(self, component: str, path: str, port: int, log_path: Path) -> None:
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        proc = self._atlas_proc if component == "atlas" else self._memoryos_proc
        url = f"http://127.0.0.1:{port}{path}"
        last_error = ""
        while time.monotonic() < deadline:
            assert proc is not None
            if proc.poll() is not None:
                raise RuntimeError(
                    f"{component} 子进程在健康等待期间退出 (code={proc.returncode})。\n"
                    f"日志尾部:\n{_tail(log_path)}"
                )
            try:
                response = httpx.get(url, timeout=2.0)
                if response.status_code == 200:
                    return
                last_error = f"HTTP {response.status_code}: {response.text[:200]}"
            except httpx.TransportError as exc:
                last_error = f"transport: {exc}"
            time.sleep(0.3)
        raise RuntimeError(
            f"{component} 在 {HEALTH_TIMEOUT_S:.0f}s 内未就绪 ({url})；最后错误: {last_error}\n"
            f"日志尾部:\n{_tail(log_path)}"
        )

    # ------------------------------------------------------------------ api

    def default_context(self) -> dict[str, Any]:
        """Default TEST MemoryContext (01_contracts.md §2) injected when missing."""
        return {
            "owner_id": "owner-fixture",
            "memory_subject_id": "atlas-fixture",
            "client_id": "atlas-desktop",
            "actor_id": "atlas-main",
            "runtime_session_id": f"chat-{uuid.uuid4().hex[:8]}",
            "task_id": None,
            "project_id": None,
            "environment_id": "windows-fixture",
            "model_deployment_id": "model-fixture",
        }

    def api(self, method: str, path: str, json: Any = None,
            params: dict[str, Any] | None = None) -> httpx.Response:
        """Real HTTP call routed by prefix: /v1/* → MemoryOS, /api/* → Atlas.

        POST /v1/unified/* bodies without a ``context`` get the default TEST
        MemoryContext injected; an explicitly provided ``context`` field is
        preserved verbatim so negative cases still reach the real service.
        """
        if path.startswith("/v1/"):
            base, headers = self.memoryos_url, {"Authorization": f"Bearer {TEST_INTERNAL_TOKEN}"}
            if (method.upper() == "POST" and path.startswith("/v1/unified/")
                    and isinstance(json, dict) and "context" not in json):
                json = {**json, "context": self.default_context()}
        elif path.startswith("/api/"):
            base, headers = self.atlas_url, {"x-atlas-api-token": ATLAS_API_TOKEN}
        else:
            raise ValueError(f"path 必须以 /v1/ 或 /api/ 开头: {path}")
        return httpx.request(method, base + path, json=json, params=params,
                             headers=headers, timeout=30.0)

    # ------------------------------------------------------------------ chat

    def chat(self, text: str, session_id: str | None = None, *,
             timeout: float = 90.0) -> dict[str, Any]:
        """Drive the real WebSocket /ws/chat path end to end.

        Sends ``run.start`` over the actual protocol (runtime_ws_router.py →
        run_drive._handle_run_start → orchestrator.run → run_phases.execute_run)
        and collects real envelopes until a terminal event. ``memory_refs`` is
        extracted from real events only — the current Runtime Event Protocol
        carries no memory-reference events, so it stays an empty list with an
        explicit note rather than anything assembled from expectations.
        """
        conversation_id = session_id or self._new_conversation()
        assert self._fake is not None
        run_id = uuid.uuid4().hex
        url = (self.atlas_url.replace("http", "ws", 1) + "/ws/chat")
        start_message = {
            "type": "run.start", "run_id": run_id, "content": text,
            "conversation_id": conversation_id, "model": MODEL_ID,
            "workspace": str(self.workspace),
        }
        from websockets.sync.client import connect as ws_connect

        events: list[dict[str, Any]] = []
        with ws_connect(url, additional_headers={"x-atlas-api-token": ATLAS_API_TOKEN},
                        max_size=8_000_000, close_timeout=5) as ws:
            ws.send(json.dumps(start_message))
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"chat 运行 {run_id} 超时（{timeout:.0f}s）")
                envelope = json.loads(ws.recv(timeout=remaining))
                events.append(envelope)
                if (envelope.get("run_id") == run_id
                        and envelope.get("event") in TERMINAL_EVENTS):
                    break
        return self._summarize_run(run_id, conversation_id, events)

    def _new_conversation(self) -> str:
        response = self.api("POST", "/api/conversations", json={"title": "UM chat"})
        if response.status_code != 200:
            raise RuntimeError(f"创建会话失败: {response.status_code} {response.text[:300]}")
        return str(response.json()["id"])

    def _summarize_run(self, run_id: str, conversation_id: str,
                       events: list[dict[str, Any]]) -> dict[str, Any]:
        counts: dict[str, int] = {}
        reply = ""
        deltas: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        terminal = None
        for envelope in events:
            event = envelope.get("event", "")
            counts[event] = counts.get(event, 0) + 1
            data = envelope.get("data", {}) or {}
            if event == "message.completed":
                reply = str(data.get("content", ""))
            elif event == "message.delta":
                deltas.append(str(data.get("content", "")))
            elif event == "tool.completed":
                tool_calls.append({
                    "tool_call_id": data.get("tool_call_id", ""),
                    "name": data.get("name", ""),
                    "result": data.get("result", []),
                    "is_error": bool(data.get("is_error", False)),
                })
            if envelope.get("run_id") == run_id and event in TERMINAL_EVENTS:
                terminal = event
        if not reply and deltas:
            reply = "".join(deltas)
        status = {"run.completed": "completed", "run.failed": "failed",
                  "run.cancelled": "cancelled"}.get(terminal or "", "unknown")
        return {
            "run_id": run_id,
            "conversation_id": conversation_id,
            "status": status,
            "reply": reply,
            "events": counts,
            "event_count": len(events),
            "tool_calls": tool_calls,
            # Real-event extraction: the Atlas WS protocol (run_drive.py) has no
            # memory_refs / trace payload today, so these stay empty with a note
            # instead of being assembled from expected values (T00.2 rule).
            "memory_refs": [],
            "memory_refs_note": (
                "Atlas Runtime Event Protocol (run_drive.py) 当前事件不携带 "
                "memory_refs；该字段仅从真实事件提取，提取不到则保持空列表"
            ),
            "trace": {
                "source": "real-ws-events",
                "terminal_event": terminal,
                "event_types": [e.get("event", "") for e in events],
                "first_sequence": events[0].get("sequence") if events else None,
                "last_sequence": events[-1].get("sequence") if events else None,
            },
            "failure": self._failure_detail(events) if status == "failed" else None,
        }

    @staticmethod
    def _failure_detail(events: list[dict[str, Any]]) -> dict[str, Any] | None:
        for envelope in reversed(events):
            if envelope.get("event") == "run.failed":
                return envelope.get("data", {})
        return None

    # ------------------------------------------------------------------ tool

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Drive real tool dispatch (agent/tool_node.execute_tools_node).

        ``/api/tools`` is a listing-only surface, so dispatch is driven the same
        way the model drives it: a scripted ``ToolCall`` from the loopback fake
        provider flows through the real agent loop into ``execute_tools_node``.
        The resolved real tool name is read from the actual ``tool.started``
        envelope and logged; the returned receipt is the real ``tool.completed``
        payload. A capability alias that resolves to nothing is a failure, not a
        silent fake (05_acceptance_matrix.md §3).
        """
        assert self._fake is not None
        self._fake.push(ToolCall(name, dict(arguments)), Text("done"))
        run = self.chat(f"执行预置的工具调用 {name}。")
        executed = run["tool_calls"]
        if not executed:
            raise AssertionError(
                f"工具 {name} 未被真实派发（run={run['run_id']} status={run['status']} "
                f"failure={run['failure']}）"
            )
        resolved_names = [item["name"] for item in executed]
        print(f"[UMHarness] 请求工具 {name} → 解析到的真实工具名: {resolved_names}")
        return {
            "requested_name": name,
            "resolved_name": resolved_names[0],
            "resolved_names": resolved_names,
            "arguments": arguments,
            "receipts": executed,
            "run_id": run["run_id"],
            "status": run["status"],
            "is_error": any(item["is_error"] for item in executed),
        }

    # ------------------------------------------------------------------ lifecycle

    def restart(self, component: str) -> None:
        """Terminate + respawn one real subprocess; data directories unchanged."""
        if component not in {"atlas", "memoryos"}:
            raise ValueError(f"未知组件: {component}（可用: atlas, memoryos）")
        proc = self._atlas_proc if component == "atlas" else self._memoryos_proc
        log_handle = (self._atlas_log_handle if component == "atlas"
                      else self._memoryos_log_handle)
        self._terminate(proc, log_handle)
        port = self.runtime_manifest[f"{component}_port"]
        if component == "atlas":
            self._atlas_log_handle = (self.root / "logs" / f"{component}.log").open("ab")
            self._atlas_proc = subprocess.Popen(
                self._atlas_command(port), cwd=str(self.root / "cwd-atlas"),
                env=self._atlas_env(self.atlas_data), stdout=self._atlas_log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.runtime_manifest["atlas_pid"] = self._atlas_proc.pid
            self._wait_health("atlas", "/api/health", port,
                              self.root / "logs" / "atlas.log")
        else:
            self._memoryos_log_handle = (self.root / "logs" / f"{component}.log").open("ab")
            self._memoryos_proc = subprocess.Popen(
                self._memoryos_command(port), cwd=str(self.root / "cwd-memoryos"),
                env=self._memoryos_env(self.memoryos_data), stdout=self._memoryos_log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.runtime_manifest["memoryos_pid"] = self._memoryos_proc.pid
            self._wait_health("memoryos", "/v1/health", port,
                              self.root / "logs" / "memoryos.log")
        self._restarts.append({
            "component": component, "port": port,
            "at": datetime.now(UTC).isoformat(),
            "data_dir_unchanged": True,
        })
        self._write_manifest_snapshot()

    # ------------------------------------------------------------------ faults

    def fault(self, name: str, enabled: bool) -> None:
        """Test-runtime fault registry. Unwired names raise, never silently no-op."""
        wired = {
            "service_down": lambda on: self._memoryos_down() if on else None,
            "service_up": lambda on: self._memoryos_up() if on else None,
        }
        if name not in wired:
            raise NotImplementedError(
                f"故障 '{name}' 未接线；UMHarness 当前已接线: {sorted(wired)}"
            )
        wired[name](enabled)
        self._faults[name] = {
            "enabled": enabled, "applied_at": datetime.now(UTC).isoformat(),
        }
        self._write_manifest_snapshot()

    def _memoryos_down(self) -> None:
        proc = self._memoryos_proc
        if proc is not None and proc.poll() is None:
            self._terminate(proc, self._memoryos_log_handle)
        self.runtime_manifest["memoryos_pid"] = None

    def _memoryos_up(self) -> None:
        if self._memoryos_proc is not None and self._memoryos_proc.poll() is None:
            return
        port = self.runtime_manifest["memoryos_port"]
        self._memoryos_log_handle = (self.root / "logs" / "memoryos.log").open("ab")
        self._memoryos_proc = subprocess.Popen(
            self._memoryos_command(port), cwd=str(self.root / "cwd-memoryos"),
            env=self._memoryos_env(self.memoryos_data), stdout=self._memoryos_log_handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.runtime_manifest["memoryos_pid"] = self._memoryos_proc.pid
        self._wait_health("memoryos", "/v1/health", port,
                          self.root / "logs" / "memoryos.log")

    # ------------------------------------------------------------------ seeds

    def seed(self, name: str) -> dict[str, Any]:
        """Load a frozen seed pack from tests/fixtures/unified_memory/seeds/.

        UM00 read-only branch kept as fallback: when the unified API is not
        reachable the records and observation batch are returned for inspection
        only. T01.2: when ``GET /v1/unified/status`` answers 200, the batch is
        POSTed to the real ``/v1/unified/observe`` entry point and the result
        carries ``created`` / ``duplicates`` / ``record_map`` — re-seeding the
        same pack replays idempotently (created=0, identical record_map).
        """
        path = SEEDS_DIR / f"{name}.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"seed '{name}' 不存在: {path}（可用: "
                f"{sorted(p.stem for p in SEEDS_DIR.glob('*.jsonl'))}）"
            )
        records: list[dict[str, Any]] = []
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            records.append(json.loads(line))
        ground_truth = {str(r.get("key", f"line-{i}")): r.get("ground_truth")
                        for i, r in enumerate(records)}
        observation_batch = {
            "contract_version": "UM-WIN-1.0",
            "event_class": EVENT_CLASS,
            # 重放幂等要求 context 逐字节稳定：runtime_session_id 由种子名派生，
            # 不用 default_context 的随机会话 ID（否则二次 seed 必然 409）。
            "context": {**self.default_context(),
                        "runtime_session_id": f"seed-{name}"},
            "observations": [],
        }
        hash_normalized = 0
        for obs in (obs for r in records for obs in r.get("observations", [])):
            normalized = dict(obs)
            # §2：夹具字面量哈希不得作为校验依据 —— seed 装配时按当前契约规则
            # 重算 content_hash（UM00 冻结夹具早于 T01.1 定稿的哈希字段集）。
            recomputed = observation_content_hash(normalized)
            if normalized.get("content_hash") != recomputed:
                hash_normalized += 1
            normalized["content_hash"] = recomputed
            observation_batch["observations"].append(normalized)
        result: dict[str, Any] = {
            "name": name,
            "source": str(path),
            "records": records,
            "record_keys": [str(r.get("key", f"line-{i}")) for i, r in enumerate(records)],
            "ground_truth": ground_truth,
            "observation_batch": observation_batch,
            "hash_normalized": hash_normalized,
        }
        # T01.2：统一 API 可用 → 真实导入（幂等）；不可用 → 保留 UM00 只读分支。
        try:
            status = self.api("GET", "/v1/unified/status")
        except Exception:  # noqa: BLE001 — 服务未起时按只读分支处理
            status = None
        if status is not None and status.status_code == 200:
            ack_response = self.api("POST", "/v1/unified/observe",
                                    json=observation_batch)
            if ack_response.status_code in (200, 201):
                ack = ack_response.json()
                memory_by_seid = {
                    str(r.get("source_event_id")): r.get("memory_id")
                    for r in (ack.get("memory_projection") or {}).get("receipts", [])
                }
                record_map: dict[str, str] = {}
                for receipt in ack.get("receipts", []):
                    seid = str(receipt.get("source_event_id"))
                    memory_id = memory_by_seid.get(seid)
                    record_map[seid] = (f"memory:{memory_id}" if memory_id
                                        else f"episode:{receipt.get('event_id')}")
                result.update({
                    "ingested": True,
                    "created": int(ack.get("created") or 0),
                    "duplicates": int(ack.get("duplicates") or 0),
                    "record_map": record_map,
                })
            else:
                result.update({"ingested": False,
                               "ingest_error": f"HTTP {ack_response.status_code}"})
        else:
            result.update({"ingested": False,
                           "ingest_note": "unified API 不可用；UM00 只读分支"})
        return result

    # ------------------------------------------------------------------ stop

    def stop(self) -> None:
        """Terminate children (Windows: terminate→kill), verify release, clean up."""
        if self.stopped:
            return
        self.stopped = True
        leftover: list[str] = []
        for component, proc, handle in (
            ("atlas", self._atlas_proc, self._atlas_log_handle),
            ("memoryos", self._memoryos_proc, self._memoryos_log_handle),
        ):
            self._terminate(proc, handle)
            pid = self.runtime_manifest.get(f"{component}_pid")
            if pid is not None and self._pid_alive(pid):
                leftover.append(f"{component}:{pid}")
            if proc is not None:
                self.runtime_manifest[f"{component}_pid"] = proc.pid
        for component in ("atlas", "memoryos"):
            port = self.runtime_manifest.get(f"{component}_port")
            if port is not None and not self._wait_port_free(int(port)):
                leftover.append(f"port:{component}:{port}")
        self.runtime_manifest["stopped_at"] = datetime.now(UTC).isoformat()
        self.runtime_manifest["stop_leftovers"] = leftover
        # Keep logs in artifacts, remove the disposable runtime tree.
        try:
            self._keep_logs()
        finally:
            shutil.rmtree(self.root, ignore_errors=True)
        if leftover:
            raise RuntimeError(f"停止后仍有残留: {leftover}")

    def _terminate(self, proc: subprocess.Popen | None, log_handle: Any) -> None:
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=STOP_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                proc.kill()
                try:
                    proc.wait(timeout=STOP_TIMEOUT_S)
                except subprocess.TimeoutExpired:
                    pass
        if log_handle is not None:
            try:
                log_handle.flush()
                log_handle.close()
            except (OSError, ValueError):
                pass
            if proc is self._atlas_proc:
                self._atlas_log_handle = None
            else:
                self._memoryos_log_handle = None

    @staticmethod
    def _pid_alive(pid: int | None) -> bool:
        if not pid:
            return False
        try:
            import psutil

            return psutil.pid_exists(int(pid))
        except ImportError:
            output = subprocess.run(
                ["tasklist", "/FI", f"PID eq {int(pid)}"], capture_output=True, text=True,
                check=False,
            ).stdout
            return str(pid) in output

    @staticmethod
    def _port_free(port: int) -> bool:
        """Connect-probe: connection refused means nothing is listening."""
        with socket.socket() as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(("127.0.0.1", port))
                return False
            except OSError:
                return True

    @classmethod
    def _wait_port_free(cls, port: int, timeout: float = 10.0) -> bool:
        """Windows may lag a few seconds releasing a killed process's port."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cls._port_free(port):
                return True
            time.sleep(0.3)
        return cls._port_free(port)

    def _keep_logs(self) -> None:
        logs_dir = self.root / "logs"
        if not logs_dir.is_dir():
            return
        kept = self.artifacts_base / f"logs-{Path(self.root).name}"
        kept.mkdir(parents=True, exist_ok=True)
        for log_file in logs_dir.glob("*.log"):
            target = kept / log_file.name
            try:
                shutil.copy2(log_file, target)
                self._logs_kept[log_file.stem] = target
            except OSError:
                continue
        self.runtime_manifest["logs"] = {
            name: str(path) for name, path in self._logs_kept.items()
        }

    def _write_manifest_snapshot(self) -> None:
        try:
            (self.root / "runtime_manifest.json").write_text(
                json.dumps(self.runtime_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ------------------------------------------------------------------ misc

    def scenario_kind(self, letter: str) -> str:
        return _SCENARIO_LETTERS[letter]

    def __enter__(self) -> "UMHarness":
        if not self.started:
            self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    def __del__(self) -> None:
        if self.started and not self.stopped:
            try:
                self.stop()
            except Exception:
                pass
