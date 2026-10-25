"""Prove dashboard access is provisioned by a live backend, across CLI data roots."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u25-dashboard-") as temporary:
        base = Path(temporary)
        backend_root, cli_root = base / "running-backend", base / "cli-profile"
        (backend_root / "data").mkdir(parents=True)
        (cli_root / "data").mkdir(parents=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]

        backend_env = os.environ.copy()
        backend_env["ATLAS_ROOT"] = str(backend_root)
        backend_env["ATLAS_DATA_DIR"] = str(backend_root)
        backend_env["ATLAS_FIXTURE_PORT"] = str(port)
        backend_env["PYTHONPATH"] = str(CORE) + os.pathsep + backend_env.get("PYTHONPATH", "")
        backend_env["PYTHONIOENCODING"] = "utf-8"
        backend = subprocess.Popen(
            [sys.executable, str(CORE / "scripts" / "dashboard_fixture_server.py")],
            cwd=ROOT, env=backend_env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if backend.poll() is not None:
                    raise RuntimeError("live dashboard fixture exited before health became ready")
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1) as response:
                        if response.status == 200:
                            break
                except OSError:
                    time.sleep(0.2)
            else:
                raise TimeoutError("live dashboard fixture did not start")

            cli_env = os.environ.copy()
            cli_env["ATLAS_ROOT"] = str(cli_root)
            cli_env.pop("ATLAS_DATA_DIR", None)
            cli_env["PYTHONIOENCODING"] = "utf-8"
            cli_env["PYTHONPATH"] = str(CORE) + os.pathsep + cli_env.get("PYTHONPATH", "")
            started = subprocess.run(
                [sys.executable, "-m", "atlas.cli", "dashboard", "start", "--port", str(port)],
                cwd=ROOT, env=cli_env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=15,
            )
            if started.returncode:
                raise RuntimeError(f"CLI dashboard start failed: {started.stderr or started.stdout}")
            match = re.search(r"http://127\.0\.0\.1:\d+/dashboard#([^\s]+)", started.stdout)
            if not match:
                raise RuntimeError(f"CLI did not print a complete dashboard URL: {started.stdout!r}")
            token = match.group(1)
            sessions = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/dashboard/sessions",
                headers={"X-Atlas-Dashboard-Token": token},
            )
            with urllib.request.urlopen(sessions, timeout=4) as response:
                rows = json.loads(response.read().decode("utf-8"))
            if not rows or rows[0].get("title") != "Live dashboard scenario":
                raise AssertionError(f"running service did not return its session data: {rows}")
            backend_record = backend_root / "data" / "runtime" / "dashboard.json"
            cli_record = cli_root / "data" / "runtime" / "dashboard.json"
            if not backend_record.is_file() or cli_record.exists():
                raise AssertionError("dashboard token was not written exclusively by the running backend")
            backend_record_data = json.loads(backend_record.read_text(encoding="utf-8"))
            if int(started.stdout.split("PID=", 1)[1].split()[0]) != backend_record_data["pid"]:
                raise AssertionError("CLI did not report the live backend PID")
            print("U25 live dashboard: CLI token issued by running backend; session API returned fixture data; separate DATA_ROOT verified")
        finally:
            backend.terminate()
            try:
                backend.wait(timeout=8)
            except subprocess.TimeoutExpired:
                backend.kill()
                backend.wait(timeout=4)


if __name__ == "__main__":
    main()
