"""Surface safe dependency-download diagnostics from real MCP child failures."""

from __future__ import annotations

import sys

import httpx
import pytest

from atlas.tools.mcp_client import MCPClient, MCPServerConfig


async def test_stdio_tls_failure_reports_certificate_error_without_echoing_stderr(tmp_path):
    script = tmp_path / "failed_server.py"
    secret = "sk-private-not-for-the-ui"
    script.write_text(
        "import sys\n"
        f"sys.stderr.write({secret!r} + '\\n')\n"
        "sys.stderr.write('npm error code ERR_TLS_CERT_ALTNAME_INVALID\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    client = MCPClient()
    config = MCPServerConfig(name="tls-failure", command=sys.executable, args=[str(script)])

    with pytest.raises(Exception) as caught:
        await client._connect_server(config)

    reason = client.get_runtime_status()["servers"][0]["blocking_reason"]
    assert "ERR_TLS_CERT_ALTNAME_INVALID" in str(caught.value)
    assert "ERR_TLS_CERT_ALTNAME_INVALID" in reason
    assert "certificate" in reason.lower()
    assert secret not in str(caught.value)
    assert secret not in reason
    assert str(script) not in reason


async def test_unrecognized_stdio_failure_does_not_expose_child_secrets(tmp_path):
    script = tmp_path / "failed_server.py"
    secret = "private-password-from-child"
    script.write_text(f"import sys\nsys.stderr.write({secret!r})\nsys.exit(1)\n", encoding="utf-8")
    client = MCPClient()

    with pytest.raises(Exception):
        await client._connect_server(
            MCPServerConfig(name="other-failure", command=sys.executable, args=[str(script)])
        )

    reason = client.get_runtime_status()["servers"][0]["blocking_reason"]
    assert secret not in reason
    assert "failed during launch or initialization" in reason


async def test_add_mcp_server_returns_safe_tls_diagnostic_and_closes_stderr_log(
    tmp_path, monkeypatch
):
    import atlas.tools.mcp_client as mcp_client_module
    from atlas import server

    script = tmp_path / "failed_server.py"
    secret = "sk-api-child-private-value"
    script.write_text(
        "import sys\n"
        f"sys.stderr.write({secret!r} + '\\n')\n"
        "sys.stderr.write('npm error code ERR_TLS_CERT_ALTNAME_INVALID\\n')\n"
        "sys.stderr.flush()\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )

    stderr_logs = []
    create_temp_file = mcp_client_module.tempfile.TemporaryFile

    def capture_temp_file(*args, **kwargs):
        stderr_log = create_temp_file(*args, **kwargs)
        stderr_logs.append(stderr_log)
        return stderr_log

    monkeypatch.setattr(mcp_client_module.tempfile, "TemporaryFile", capture_temp_file)
    monkeypatch.setattr(server, "mcp_client", MCPClient())

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/mcp/servers",
            json={
                "name": "tls-api-failure",
                "transport": "stdio",
                "command": sys.executable,
                "args": [str(script)],
            },
        )

    detail = response.json()["detail"]
    assert response.status_code == 500
    assert "ERR_TLS_CERT_ALTNAME_INVALID" in detail
    assert "certificate hostname mismatch" in detail
    assert secret not in detail
    assert str(script) not in detail
    assert server.mcp_client.get_server_names() == []
    status = server.mcp_client.get_runtime_status()["servers"][0]
    assert status["state"] == "failed"
    assert status["connected"] is False
    assert secret not in status["blocking_reason"]
    assert len(stderr_logs) == 1
    assert stderr_logs[0].closed
