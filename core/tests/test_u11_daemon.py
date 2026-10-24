from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from atlas import cli


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
