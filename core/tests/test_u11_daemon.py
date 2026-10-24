from __future__ import annotations

import threading
import os
import socket
import subprocess
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from atlas import cli

ROOT = Path(__file__).resolve().parents[2]


def test_daemon_refuses_to_claim_an_existing_atlas_server(tmp_path: Path, monkeypatch) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/api/health":
                self.send_error(404)
                return
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    control = tmp_path / "runtime" / "daemon.json"
    monkeypatch.setattr(cli, "_daemon_control_file", lambda: control)
    monkeypatch.setattr("atlas.config.get_config", lambda: SimpleNamespace(server_port=server.server_port))
    try:
        result = CliRunner().invoke(cli.main, ["daemon", "start"])
        assert result.exit_code != 0
        assert "already serving port" in result.output
        assert not control.exists()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_daemon_cli_exposes_lifecycle_and_startup_commands() -> None:
    result = CliRunner().invoke(cli.main, ["daemon", "--help"])
    assert result.exit_code == 0
    for command in ("start", "stop", "status", "enable-startup", "disable-startup"):
        assert command in result.output


def test_daemon_real_start_status_and_stop(tmp_path: Path) -> None:
    """Exercise the detached server and DBOS lifecycle using an isolated data root."""
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    env = {
        **os.environ,
        "ATLAS_ROOT": str(tmp_path),
        "PYTHONPATH": os.pathsep.join((str(ROOT / "core"), os.environ.get("PYTHONPATH", ""))),
    }

    def invoke(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "atlas.cli", *args], cwd=ROOT,
            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90,
        )

    started = invoke("daemon", "start", "--port", str(port))
    assert started.returncode == 0, started.stdout + started.stderr
    try:
        status = invoke("daemon", "status")
        assert status.returncode == 0 and "daemon healthy" in status.stdout.lower(), status.stdout + status.stderr
    finally:
        stopped = invoke("daemon", "stop")
    assert stopped.returncode == 0 and "daemon stopped" in stopped.stdout.lower(), stopped.stdout + stopped.stderr

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                time.sleep(0.1)
        except OSError:
            break
    else:
        raise AssertionError("daemon server port remained open after graceful stop")
