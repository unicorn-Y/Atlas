from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from real_memory import RealMemoryService


class _NoSuchProcess(Exception):
    pass


class _FakeProcess:
    def __init__(self, pid: int, created: float, children: list[int] | None = None) -> None:
        self.pid = pid
        self.created = created
        self.child_pids = children or []
        self.alive = True
        self.terminated = False
        self.killed = False

    def create_time(self) -> float:
        return self.created

    def children(self, recursive: bool = False) -> list["_FakeProcess"]:
        result: list[_FakeProcess] = []
        pending = list(self.child_pids)
        while pending:
            child_pid = pending.pop(0)
            child = _PROCESSES[child_pid]
            result.append(child)
            if recursive:
                pending.extend(child.child_pids)
        return result

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False

    def kill(self) -> None:
        self.killed = True
        self.alive = False


_PROCESSES: dict[int, _FakeProcess] = {}


class _FakePsutil:
    NoSuchProcess = _NoSuchProcess

    @staticmethod
    def Process(pid: int) -> _FakeProcess:
        process = _PROCESSES.get(pid)
        if process is None or not process.alive:
            raise _NoSuchProcess(pid)
        return process

    @staticmethod
    def wait_procs(processes, timeout: float = 0):
        gone = [process for process in processes if not process.alive]
        alive = [process for process in processes if process.alive]
        return gone, alive


class RealMemoryProcessLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        _PROCESSES.clear()

    def test_stop_terminates_only_identity_checked_owned_process_tree(self) -> None:
        root = _FakeProcess(10, 100.0, [11])
        child = _FakeProcess(11, 101.0, [12])
        grandchild = _FakeProcess(12, 102.0)
        unrelated = _FakeProcess(20, 103.0)
        _PROCESSES.update({10: root, 11: child, 12: grandchild, 20: unrelated})
        service = RealMemoryService(Path("D:/Temp/f1d-process-test"))
        service.proc = SimpleNamespace(pid=10, wait=lambda timeout=None: 0)

        with patch.dict(sys.modules, {"psutil": _FakePsutil}):
            service._capture_owned_process_tree()
            service.stop()

        self.assertFalse(root.alive)
        self.assertFalse(child.alive)
        self.assertFalse(grandchild.alive)
        self.assertTrue(unrelated.alive)

    def test_stop_skips_pid_reused_by_a_different_process_instance(self) -> None:
        reused = _FakeProcess(31, 201.0)
        _PROCESSES[31] = reused
        service = RealMemoryService(Path("D:/Temp/f1d-process-test"))
        service.proc = None
        service._owned_processes = {31: 200.0}

        with patch.dict(sys.modules, {"psutil": _FakePsutil}):
            service._terminate_owned_process_tree()

        self.assertTrue(reused.alive)
        self.assertFalse(reused.terminated)
        self.assertFalse(reused.killed)


if __name__ == "__main__":
    unittest.main()
