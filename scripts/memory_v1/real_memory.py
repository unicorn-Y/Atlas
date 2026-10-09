"""S8 评测真实记忆层：真 MemoryOS 服务 + 真 observe + 真 assemble_recall_context。

评测原先只把观察留在进程内列表、用手搓字符串冒充装配（`assembled_refs` 是合成的
`ref_<场景>_<轮>`）。本模块提供真管线，供 eval_scenarios 使用：

  1. `RealMemoryService`：起/停一个真 MemoryOS (uvicorn) 子进程，绑定隔离数据根。
  2. `push_observations`：把观察（观察者抽取结果 / 场景预置历史）经真 facade 落库。
  3. `recall`：调真 `assemble_recall_context`，返回真实装配结果（refs + 记忆块）。
  4. `records` / `erase`：读回与硬擦除，供编辑/删除场景走真存储。

设计约束：绝不出网、绝不碰生产根；一切路径来自 `enforce_isolation` 写入的环境变量。
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

_MEMORYOS_REPO = Path(os.environ.get("MEMORYOS_REPO", r"D:\MemoryOS"))
_ATLAS_REPO = Path(os.environ.get("ATLAS_REPO", r"D:\Atlas"))
DEFAULT_SERVICE_PYTHON = _MEMORYOS_REPO / "service" / ".venv" / "Scripts" / "python.exe"

# 与 core/tests/unified_memory/harness.py 保持一致的服务端契约常量
TEST_INTERNAL_TOKEN = "test-internal-token"
TEST_OWNER_TOKEN = "test-owner-token"
SUBJECT = "atlas-fixture"
HEALTH_TIMEOUT_S = 90.0


def _same_process_instance(expected_creation_time: float, actual_creation_time: float) -> bool:
    return abs(float(expected_creation_time) - float(actual_creation_time)) < 0.001


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _normalize_iso(value: str) -> str:
    """归一为带时区偏移的完整 ISO 时间（契约 §2：不接受 naive 时间）。"""
    v = (value or "").strip()
    if not v:
        return "2026-10-08T10:00:00+08:00"
    if "T" not in v:
        v = v.replace(" ", "T")
    # 已有完整时间部分（含 T 与 HH:MM）→ 只补时区
    if "T" in v and len(v.split("T", 1)[1]) >= 5:
        if not (v.endswith("Z") or "+" in v.split("T", 1)[1]):
            v += "+08:00"
        return v
    # 纯日期（YYYY-MM-DD）→ 补 00:00:00 + 时区
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return f"{v}T00:00:00+08:00"
    if not (v.endswith("Z") or "+" in v):
        v += "+08:00"
    return v


def to_observation(
    text: str,
    *,
    session_id: str,
    turn_index: int,
    idx: int,
    occurred_at: str,
    source_kind: str = "ATLAS_USER_MESSAGE",
) -> dict[str, Any]:
    """把一段观察文本转成 MemoryOS 契约观察载荷。"""
    obj = f"eval-{session_id}-{turn_index}-{idx}"
    return {
        "source_event_id": f"atlas:{source_kind}:{obj}:1:UPSERT",
        "source_kind": source_kind,
        "source_object_id": obj,
        "source_revision": "1",
        "event_action": "UPSERT",
        "occurred_at": _normalize_iso(occurred_at),
        "source_timezone": "Asia/Hong_Kong",
        "time_status": "KNOWN",
        "speaker_role": "USER",
        "epistemic_kind": "USER_ASSERTED",
        "content": {"text": text},
        "locator": {"kind": "MESSAGE", "value": f"{session_id}/{turn_index}"},
        "media_refs": [],
        "derived_from": [],
    }


class RealMemoryService:
    """真 MemoryOS 服务生命周期 + 真 facade 句柄。"""

    def __init__(
        self,
        data_root: Path,
        *,
        subject_id: str = SUBJECT,
        subject_aliases: str = "subject-default",
        service_python: Path | str | None = None,
    ) -> None:
        self.data_root = data_root
        self.subject_id = subject_id
        self.subject_aliases = subject_aliases
        self.service_python = Path(service_python).resolve() if service_python else (
            DEFAULT_SERVICE_PYTHON
        )
        self.port = free_port()
        self.proc: subprocess.Popen[bytes] | None = None
        self._owned_processes: dict[int, float] = {}
        self._log = None
        self._facade = None

    # ---------------------------------------------------------------- lifecycle
    def start(self) -> "RealMemoryService":
        try:
            import psutil  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "psutil is required to track and stop the isolated MemoryOS process tree safely"
            ) from exc
        db_root = self.data_root / "db"
        db_root.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        env.update({
            "MEMORYOS_DATA_ROOT": str(self.data_root),
            "MEMORYOS_DB_PATH": str(db_root / "memoryos.sqlite3"),
            "MEMORYOS_INTERNAL_TOKEN": TEST_INTERNAL_TOKEN,
            "MEMORYOS_OWNER_TOKEN": TEST_OWNER_TOKEN,
            "MEMORYOS_MEMORY_SUBJECT_ID": self.subject_id,
            "MEMORYOS_MEMORY_SUBJECT_ALIASES": self.subject_aliases,
            "NO_PROXY": "127.0.0.1,localhost",
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONPATH": str(_MEMORYOS_REPO / "service"),
        })
        if not self.service_python.is_file():
            raise FileNotFoundError(
                f"MemoryOS service interpreter does not exist: {self.service_python}"
            )
        self._log = open(self.data_root / "memoryos.log", "wb")
        self.proc = subprocess.Popen(
            [str(self.service_python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(self.port)],
            cwd=str(_MEMORYOS_REPO / "service"), env=env,
            stdout=self._log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._capture_owned_process_tree()
        self._wait_health()
        return self

    def _wait_health(self) -> None:
        import urllib.request

        url = f"http://127.0.0.1:{self.port}/v1/health"
        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        last = ""
        while time.monotonic() < deadline:
            assert self.proc is not None
            self._capture_owned_process_tree()
            if self.proc.poll() is not None:
                raise RuntimeError(
                    f"MemoryOS 子进程提前退出 (code={self.proc.returncode})；日志尾部:\n{self.log_tail()}"
                )
            try:
                with urllib.request.urlopen(url, timeout=2) as r:
                    if r.status == 200:
                        return
                    last = f"HTTP {r.status}"
            except Exception as exc:  # noqa: BLE001
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(0.3)
        raise RuntimeError(f"MemoryOS 在 {HEALTH_TIMEOUT_S:.0f}s 内未就绪 ({url})；最后错误 {last}\n{self.log_tail()}")

    def log_tail(self, limit: int = 3000) -> str:
        p = self.data_root / "memoryos.log"
        if p.exists():
            return p.read_text(encoding="utf-8", errors="replace")[-limit:]
        return "(no log)"

    def stop(self) -> None:
        proc = self.proc
        try:
            if proc is not None:
                self._capture_owned_process_tree()
                self._terminate_owned_process_tree()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired as exc:
                    raise RuntimeError(
                        f"MemoryOS root process {proc.pid} remains after identity-checked tree cleanup"
                    ) from exc
                self.proc = None
        finally:
            if self._log is not None:
                try:
                    self._log.close()
                except Exception:  # noqa: BLE001
                    pass
                self._log = None

    def _capture_owned_process_tree(self) -> None:
        """Remember PID + creation time for the service root and its descendants."""
        if self.proc is None:
            return
        import psutil

        try:
            root = psutil.Process(self.proc.pid)
        except psutil.NoSuchProcess:
            if self.proc.poll() is None:
                raise RuntimeError(
                    f"Cannot verify identity for live MemoryOS process {self.proc.pid}"
                )
            return

        root_created = root.create_time()
        previous_root_created = self._owned_processes.get(root.pid)
        if previous_root_created is not None and not _same_process_instance(
            previous_root_created, root_created
        ):
            return
        self._owned_processes[root.pid] = root_created
        for child in root.children(recursive=True):
            try:
                self._owned_processes[child.pid] = child.create_time()
            except psutil.NoSuchProcess:
                continue

    def _terminate_owned_process_tree(self) -> None:
        """Stop only saved process instances; never signal a PID after reuse."""
        if not self._owned_processes:
            return
        import psutil

        processes = []
        for pid, created in self._owned_processes.items():
            try:
                process = psutil.Process(pid)
                if _same_process_instance(created, process.create_time()):
                    processes.append(process)
            except psutil.NoSuchProcess:
                continue

        for process in reversed(processes):
            try:
                if _same_process_instance(
                    self._owned_processes[process.pid], process.create_time()
                ):
                    process.terminate()
            except psutil.NoSuchProcess:
                continue

        _, alive = psutil.wait_procs(processes, timeout=5)
        for process in alive:
            try:
                if _same_process_instance(
                    self._owned_processes[process.pid], process.create_time()
                ):
                    process.kill()
            except psutil.NoSuchProcess:
                continue
        _, alive = psutil.wait_procs(alive, timeout=5)
        remaining = []
        for process in alive:
            try:
                if _same_process_instance(
                    self._owned_processes[process.pid], process.create_time()
                ):
                    remaining.append(process.pid)
            except psutil.NoSuchProcess:
                continue
        if remaining:
            raise RuntimeError(
                "MemoryOS owned processes survived identity-checked cleanup: "
                + ", ".join(map(str, sorted(remaining)))
            )

    # -------------------------------------------------------------------- facade
    def facade(self):
        """真 UnifiedMemoryFacade，指向本服务；读路径走 recall 超时保护。"""
        if self._facade is None:
            if str(_ATLAS_REPO / "core") not in sys.path:
                sys.path.insert(0, str(_ATLAS_REPO / "core"))
            from atlas.config import AtlasConfig
            from atlas.memory.unified_facade import UnifiedMemoryFacade

            cfg = AtlasConfig({"memory": {"unified": {
                "enabled": True,
                "service_url": f"http://127.0.0.1:{self.port}",
                "internal_token": TEST_INTERNAL_TOKEN,
                "subject_binding": self.subject_id,
            }}})
            self._facade = UnifiedMemoryFacade(config=cfg)
        return self._facade

    def context(self, *, session_id: str = "eval") -> dict[str, Any]:
        return self.facade().default_context(runtime_session_id=session_id)

    # ------------------------------------------------------------------- pipeline
    async def push(self, observations: list[dict[str, Any]], *, session_id: str = "eval") -> dict[str, Any]:
        """把观察经真 facade 落库（空列表跳过）。"""
        if not observations:
            return {"accepted": 0, "created": 0, "skipped": True}
        batch = {
            "contract_version": "UM-WIN-1.0",
            "event_class": "TEST",
            "context": self.context(session_id=session_id),
            "observations": observations,
        }
        return await self.facade().observe_batch(batch)

    async def recall(self, user_message: str, *, session_id: str = "eval"):
        """真召回装配（走 assemble_recall_context 真函数）。"""
        from atlas.memory.recall_context import assemble_recall_context

        return await assemble_recall_context(
            self.facade(), user_message, subject=SUBJECT, session_id=session_id,
        )

    async def records(self, *, limit: int = 200) -> list[dict[str, Any]]:
        res = await self.facade().list_records(limit=limit)
        return res.get("items", []) if isinstance(res, dict) else []

    async def aclose(self) -> None:
        if self._facade is not None:
            try:
                await self._facade.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._facade = None
