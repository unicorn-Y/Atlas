"""The is_waiting regression: a live PID must block the goal WITHOUT being killed."""

from __future__ import annotations

import os
import subprocess
import sys

from atlas.engine.goals import GoalManager


def test_is_waiting_on_live_pid_does_not_kill_it(tmp_path):
    """Regression: os.kill(pid, 0) on Windows terminated the watched process."""
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        manager = GoalManager("s1", home=tmp_path)
        manager.set("wait for the build")
        manager.wait_on(proc.pid, "build running")

        assert manager.is_waiting() is True
        assert proc.poll() is None, "probing liveness must not terminate the process"
    finally:
        proc.kill()
        proc.wait(timeout=10)


def test_is_waiting_on_dead_pid_clears_wait(tmp_path):
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait(timeout=30)
    manager = GoalManager("s1", home=tmp_path)
    manager.set("wait for the build")
    manager.wait_on(proc.pid, "build running")

    assert manager.is_waiting() is False
    assert not manager.state.waiting_on_pid, "a dead PID must clear the barrier"


def test_is_waiting_on_own_pid_is_safe(tmp_path):
    """The original crash: probing pytest's own PID killed the test runner."""
    manager = GoalManager("s1", home=tmp_path)
    manager.set("wait")
    manager.wait_on(os.getpid(), "self")

    assert manager.is_waiting() is True


def test_is_waiting_false_without_goal(tmp_path):
    assert GoalManager("empty", home=tmp_path).is_waiting() is False


def test_pid_alive_rejects_garbage():
    from atlas.engine.goal_loop import pid_alive

    assert pid_alive(0) is False
    assert pid_alive(-1) is False
