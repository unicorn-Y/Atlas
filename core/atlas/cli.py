"""Atlas CLI — command-line entry point."""

import asyncio
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any, TextIO

import click

# The CLI's stdout is data (stream-json lines, doctor --json); every log sink in
# a CLI process therefore belongs on stderr. structlog's default factory prints
# to stdout, which would corrupt parsed output, so pin it before anything logs.
# Only affects processes launched through this module (serve/chat/hub/run/doctor).
import structlog

structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))

class _LazyConsole:
    def __init__(self) -> None:
        self._console = None

    def __getattr__(self, name: str) -> Any:
        if self._console is None:
            from rich.console import Console

            self._console = Console()
        return getattr(self._console, name)


_CLI_ATTACH_MAX_BYTES = 5 * 1024 * 1024


console = _LazyConsole()


@click.group()
def main() -> None:
    """Atlas — All-in-one AI Personal Assistant."""
    pass


@main.command("memory-bench")
@click.option("--dataset", type=click.Path(exists=True, dir_okay=False, path_type=Path), default=None,
              help="Versioned benchmark dataset JSON; defaults to the bundled v1 corpus.")
@click.option("--k", "k_values", default="1,3,5", show_default=True,
              help="Comma-separated retrieval cutoffs, for example 1,3,5.")
@click.option("--format", "output_format", type=click.Choice(["markdown", "json"]), default=None)
@click.option("--generate/--retrieval-only", default=False, show_default=True,
              help="Also ask the configured model to answer from retrieved evidence and cite record ids.")
@click.option("--model", "model_id", default=None, help="Model id for --generate; defaults to Atlas's current model.")
@click.option("--output", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Atomically write the report; .json selects JSON when --format is omitted.")
def memory_bench_command(
    dataset: Path | None, k_values: str, output_format: str | None,
    generate: bool, model_id: str | None, output: Path | None,
) -> None:
    """Evaluate isolated memory recall against a versioned local question set."""
    from atlas.memory.bench import render_markdown, run_memory_benchmark

    try:
        ks = tuple(int(value.strip()) for value in k_values.split(",") if value.strip())
        if not ks or any(value <= 0 for value in ks):
            raise ValueError("--k must contain positive integers")
        output_format = output_format or ("json" if output is not None and output.suffix.lower() == ".json" else "markdown")
        if model_id and not generate:
            raise ValueError("--model requires --generate")
        report = run_memory_benchmark(dataset, ks=ks, generate=generate, model_id=model_id)
        serialized = json.dumps(report, ensure_ascii=False, indent=2) if output_format == "json" else render_markdown(report)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix(output.suffix + ".tmp")
            temporary.write_text(serialized + "\n", encoding="utf-8")
            temporary.replace(output)
        click.echo(serialized)
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(f"记忆召回评测失败：{exc}") from exc


@main.group("security")
def security_group() -> None:
    """Audit local dependency locks and security-sensitive configuration."""


@security_group.command("audit")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
@click.option("--output", type=click.Path(path_type=Path), help="将审计报告写入文件")
def security_audit(as_json: bool, output: Path | None) -> None:
    """Offline-first CVE and configuration audit; use refresh-db to update OSV data."""
    from atlas.config import DATA_ROOT, PROJECT_ROOT
    from atlas.security_audit import audit

    report = audit(PROJECT_ROOT, DATA_ROOT / "data" / "security-osv-cache.json")
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(output)
    if as_json:
        click.echo(serialized)
    else:
        console.print(f"离线依赖审计：{report['dependency_count']} 个锁定包；漏洞数据库更新时间：{report['advisory_updated_at'] or '尚无本机快照'}")
        console.print(f"快照覆盖：{report['indexed_dependency_count']}/{report['dependency_count']}；配置/依赖发现：{len(report['findings'])} 项")
        for item in report["findings"]:
            console.print(f"[{item['severity']}] {item['id']} · {item.get('package', item.get('file', 'Atlas'))}")
            console.print(f"  证据：{item['evidence']}\n  建议：{item['recommendation']}")
        if report["dependency_coverage"] != "complete":
            console.print("依赖漏洞覆盖不完整；运行 atlas security refresh-db 更新本机 OSV 快照。")
    raise SystemExit(1 if any(item.get("package") or item["severity"] in {"high", "critical", "error"} for item in report["findings"]) else 0)


@security_group.command("refresh-db")
def security_refresh_db() -> None:
    """Download exact-version advisories from OSV and save a local offline snapshot."""
    from atlas.config import DATA_ROOT, PROJECT_ROOT
    from atlas.security_audit import refresh_advisories

    try:
        snapshot = refresh_advisories(PROJECT_ROOT, DATA_ROOT / "data" / "security-osv-cache.json")
    except Exception as exc:  # noqa: BLE001 — provide a clear command error without losing local settings
        raise click.ClickException(f"无法刷新 OSV 漏洞快照：{type(exc).__name__}: {exc}") from exc
    console.print(f"已更新本机 OSV 快照：{snapshot['package_count']} 个锁定包，时间 {snapshot['updated_at']}")


@main.group("lsp")
def lsp_group() -> None:
    """Manage local language servers and inspect project diagnostics."""


@main.group("mcp")
def mcp_group() -> None:
    """Expose Atlas capabilities to MCP clients."""


@mcp_group.command("serve")
def mcp_serve_command() -> None:
    """Run the Atlas MCP server over stdio for a local MCP client."""
    from atlas.tools.agent_bridge import main as serve_mcp

    serve_mcp()


@main.group("ide")
def ide_group() -> None:
    """Inspect editor context available to Atlas."""


@ide_group.command("context")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def ide_context_command(as_json: bool) -> None:
    """Show active file, selection, and workspace detected from this IDE terminal."""
    from atlas.ide_context import discover_ide_context

    context = asyncio.run(discover_ide_context())
    if as_json:
        click.echo(json.dumps(context, ensure_ascii=False, indent=2))
    elif context:
        console.print(json.dumps(context, ensure_ascii=False, indent=2))
    else:
        console.print(f"没有发现 IDE 环境；当前工作目录为 {Path.cwd()}。可通过 ATLAS_IDE_FILE、ATLAS_IDE_SELECTION 和 ATLAS_IDE_WORKSPACE 提供上下文。")


@lsp_group.command("status")
@click.option("--workspace", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path.cwd())
def lsp_status_command(workspace: Path) -> None:
    """List configured language servers and their installation status."""
    from atlas.config import get_config
    from atlas.lsp.servers import SERVERS, ServerContext, custom_servers
    root = str(workspace.resolve())
    configured = get_config().get("lsp.servers", {})
    configured = configured if isinstance(configured, dict) else {}
    overrides = {name: item["command"] for name, item in configured.items()
                 if isinstance(item, dict) and isinstance(item.get("command"), list) and item["command"]}
    disabled = {name for name, item in configured.items() if isinstance(item, dict) and item.get("disabled")}
    ctx = ServerContext(workspace_root=root, binary_overrides=overrides)
    for server in [*custom_servers(configured), *SERVERS]:
        if server.server_id in disabled:
            console.print(f"已停用  {server.server_id}  {', '.join(server.extensions)}")
            continue
        try:
            ready = server.build_spawn(root, ctx) is not None
        except (OSError, RuntimeError, ValueError):
            ready = False
        console.print(f"{'就绪' if ready else '未安装'}  {server.server_id}  {', '.join(server.extensions)}")


@lsp_group.command("diagnostics")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def lsp_diagnostics_command(path: Path) -> None:
    """Start the matching language server if needed and print fresh diagnostics for PATH."""
    from atlas.tools.workspace_lsp import query_lsp
    try:
        result = query_lsp(str(path.parent.resolve()), operation="diagnostics", path=path.name)
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    console.print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result.get("available"):
        raise click.ClickException(str(result.get("reason", "LSP diagnostics unavailable")))


@lsp_group.command("start")
@click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def lsp_start_command(path: Path) -> None:
    """Start the configured server for PATH and wait for its first fresh diagnostic result."""
    lsp_diagnostics_command(path)


@lsp_group.command("stop")
def lsp_stop_command() -> None:
    """Stop all local language-server processes owned by this Atlas process."""
    from atlas.lsp import shutdown_service
    shutdown_service()
    console.print("语言服务已停止。")


@main.command("review")
@click.option("--workspace", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path.cwd())
@click.option("--model", help="覆盖 Atlas 当前模型")
@click.option("--ci", is_flag=True, help="CI 非交互模式；发现 blocker/major 时退出码为 1")
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
@click.option("--output", type=click.Path(path_type=Path), help="原子写入完整 JSON 报告")
def review_command(workspace: Path, model: str | None, ci: bool, as_json: bool, output: Path | None) -> None:
    """Run parallel, read-only repository review layers over the whole Git workspace."""
    from atlas.review.engine import run_repository_review_sync
    try:
        report = run_repository_review_sync(str(workspace), model=model)
    except Exception as exc:  # noqa: BLE001 — CLI should return a clear nonzero CI failure
        raise click.ClickException(f"仓库审查失败：{type(exc).__name__}: {exc}") from exc
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_text(serialized + "\n", encoding="utf-8")
        temporary.replace(output)
    if as_json:
        click.echo(serialized)
    else:
        console.print(f"仓库审查完成：{report['file_count']} 个文件，{len(report['review_layers'])}/3 层 reviewer 完成，{len(report['findings'])} 条去重发现。")
        for finding in report["findings"]:
            console.print(f"[{finding['severity']}] {finding['file']}:{finding.get('line') or '?'} · {finding['title']} ({', '.join(finding['review_layers'])})")
        for layer, error in report["layer_errors"].items():
            console.print(f"审查层 {layer} 失败：{error}")
    if ci and (report["layer_errors"] or any(item["severity"] in {"blocker", "major"} for item in report["findings"])):
        raise SystemExit(1)


@main.command()
@click.option("--port", default=None, type=int, help="Server port (default: from config)")
@click.option("--host", default=None, help="Bind host (for example 127.0.0.1)")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(port: int | None, host: str | None, reload: bool) -> None:
    """Start the Atlas backend server."""
    import uvicorn

    from atlas.config import get_config

    cfg = get_config()
    actual_port = port or cfg.server_port
    host = host or cfg.server_host

    console.print(f"[bold]Atlas[/bold] server starting on {host}:{actual_port}...")
    uvicorn.run(
        "atlas.server:app",
        host=host,
        port=actual_port,
        reload=reload,
    )


@main.group("dashboard")
def dashboard_group() -> None:
    """Start, inspect, or stop the loopback-only browser console."""


def _dashboard_control_file() -> Path:
    from atlas.dashboard_access import control_path

    return control_path()


@main.group("channel")
def channel_group() -> None:
    """Send messages through configured channel accounts."""


@channel_group.command("send")
@click.option("--channel", "channel_name", required=True, help="registered channel id")
@click.option("--target", required=True, help="platform conversation/user destination")
@click.option("--text", "message_text", required=True, help="message content")
@click.option("--wait-seconds", default=5, type=click.IntRange(0, 300), help="wait for delivery status")
def channel_send(channel_name: str, target: str, message_text: str, wait_seconds: int) -> None:
    """Queue a message and report its durable delivery/retry state."""
    import time
    import httpx
    from atlas.config import get_config

    base = f"http://127.0.0.1:{get_config().server_port}"
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.post(f"{base}/api/channels/send", json={
                "channel": channel_name, "target": target, "text": message_text,
            })
            if not response.is_success:
                detail = response.json().get("detail", f"HTTP {response.status_code}")
                raise click.ClickException(f"渠道消息未排队：{detail}")
            submitted = response.json()
            status = {"status": submitted.get("status", "pending"), "attempts": 0,
                      "message": "消息已排队，等待投递"}
            deadline = time.monotonic() + wait_seconds
            while wait_seconds and time.monotonic() < deadline and status["status"] not in {"delivered", "dead"}:
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
                result = client.get(f"{base}/api/channels/delivery/{submitted['idempotency_key']}")
                if result.is_success:
                    status = result.json()
            console.print(f"{channel_name} → {target}: {status.get('message', status['status'])}; "
                          f"status={status['status']} attempts={status.get('attempts', 0)} "
                          f"idempotency_key={submitted['idempotency_key']}")
    except httpx.HTTPError as exc:
        raise click.ClickException(f"无法连接 Atlas 渠道网关：{type(exc).__name__}；请先启动 Atlas。") from exc


@dashboard_group.command("start")
@click.option("--port", default=None, type=int, help="Dashboard API port (default: Atlas server port)")
def dashboard_start(port: int | None) -> None:
    """Enable the local dashboard and start a loopback backend only when needed."""
    import httpx
    import secrets
    import subprocess
    import time
    from atlas.config import get_config
    from atlas.dashboard_access import read_control

    selected_port = port or get_config().server_port
    control = _dashboard_control_file()
    prior = read_control(include_expired=True)
    owns_server = bool(prior.get("owns_server"))
    shutdown_token = str(prior.get("shutdown_token") or "")
    pid = int(prior.get("pid") or 0)
    try:
        response = _daemon_request("GET", "/api/health", selected_port, timeout=1.0)
        if not response.is_success:
            raise httpx.HTTPError(f"backend returned HTTP {response.status_code}")
    except httpx.HTTPError:
        control.parent.mkdir(parents=True, exist_ok=True)
        log_path = control.parent.parent / "logs" / "dashboard.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        shutdown_token = secrets.token_urlsafe(32)
        env = {**os.environ, "ATLAS_SHUTDOWN_TOKEN": shutdown_token}
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        with log_path.open("ab") as log_file:
            process = subprocess.Popen(
                [sys.executable, "-m", "atlas.cli", "serve", "--port", str(selected_port), "--host", "127.0.0.1"],
                env=env, cwd=os.getcwd(), stdin=subprocess.DEVNULL, stdout=log_file, stderr=log_file,
                creationflags=flags, start_new_session=os.name != "nt",
            )
        pid, owns_server = process.pid, True
        deadline = time.time() + 60
        while time.time() < deadline and process.poll() is None:
            try:
                response = _daemon_request("GET", "/api/health", selected_port, timeout=1.0)
                if response.is_success:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        else:
            raise click.ClickException(f"Atlas dashboard backend failed to start; see {log_path}")

    # Provision on the live backend: it may use a different DATA_ROOT from this
    # CLI process, and that backend is the process which validates the token.
    try:
        access = _daemon_request("POST", "/api/dashboard/access", selected_port, timeout=5.0)
        if not access.is_success:
            detail = access.json().get("detail", f"HTTP {access.status_code}")
            raise click.ClickException(f"无法启用本地控制台：{detail}")
        details = access.json()
    except httpx.HTTPError as exc:
        raise click.ClickException(f"无法连接 Atlas 后端以启用本地控制台：{type(exc).__name__}") from exc
    click.echo(f"本地控制台已启动：{details['url']}")
    click.echo(f"PID={details['pid']} · 仅 loopback · 访问令牌有效至 {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(details['expires_at']))}")


@dashboard_group.command("status")
def dashboard_status() -> None:
    """Show local dashboard and backend health without printing its token."""
    import httpx
    from atlas.dashboard_access import read_control

    info = read_control()
    if not info:
        console.print("本地控制台未运行。使用 atlas dashboard start 启动。")
        return
    try:
        response = _daemon_request("GET", "/api/health", int(info["port"]), timeout=2.0)
        if not response.is_success:
            raise httpx.HTTPError(f"HTTP {response.status_code}")
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        console.print(f"控制台记录存在，但 Atlas 后端不可用：{type(exc).__name__}")
        return
    console.print(f"本地控制台已就绪：http://127.0.0.1:{info['port']}/dashboard · PID={info['pid']} · loopback only")


@dashboard_group.command("stop")
def dashboard_stop() -> None:
    """Revoke dashboard access and stop only a backend launched by this command."""
    import json as json_module
    import time
    import httpx
    from atlas.dashboard_access import control_path, revoke_access

    path = control_path()
    try:
        info = json_module.loads(path.read_text(encoding="utf-8"))
    except (OSError, json_module.JSONDecodeError):
        console.print("本地控制台未运行。")
        revoke_access()
        return
    revoke_access()
    if info.get("owns_server"):
        port = int(info.get("port", 0))
        token = str(info.get("shutdown_token") or "")
        try:
            _daemon_request("POST", "/api/runtime/shutdown", port, token=token, timeout=3.0)
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    _daemon_request("GET", "/api/health", port, timeout=0.5)
                except httpx.HTTPError:
                    break
                time.sleep(0.25)
            else:
                raise click.ClickException("Dashboard backend did not release its loopback port within 30 seconds")
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise click.ClickException(f"Dashboard backend stop failed: {type(exc).__name__}") from exc
    console.print("本地控制台访问已撤销；由 dashboard 启动的后端已清理。")


@main.group()
def daemon() -> None:
    """Manage Atlas's independent, persistent automation server."""


def _daemon_control_file() -> Path:
    from atlas.config import DATA_ROOT
    return DATA_ROOT / "data" / "runtime" / "automation-daemon.json"


def _daemon_request(method: str, path: str, port: int, *, token: str = "", timeout: float = 3.0):
    import httpx
    headers = {"X-Atlas-Backend-Shutdown-Token": token} if token else {}
    return httpx.request(method, f"http://127.0.0.1:{port}{path}", headers=headers, timeout=timeout)


@daemon.command("start")
@click.option("--port", default=None, type=int, help="API port (default: Atlas server port)")
def daemon_start(port: int | None) -> None:
    """Start a detached local server that keeps DBOS automations running after the UI exits."""
    import json as json_module
    import os
    import secrets
    import subprocess
    import time
    import httpx

    from atlas.config import get_config

    control = _daemon_control_file()
    selected_port = port or get_config().server_port
    if control.is_file():
        try:
            info = json_module.loads(control.read_text(encoding="utf-8"))
            response = _daemon_request("GET", "/api/health", int(info["port"]), timeout=1.0)
            if response.is_success:
                console.print(f"Automation daemon already running (pid={info['pid']}, port={info['port']}).")
                return
        except (OSError, ValueError, KeyError, TypeError, json_module.JSONDecodeError, httpx.HTTPError):
            pass
        control.unlink(missing_ok=True)

    try:
        occupied = _daemon_request("GET", "/api/health", selected_port, timeout=1.0)
        if occupied.is_success:
            raise click.ClickException(
                f"Atlas is already serving port {selected_port} without a daemon control record. "
                "Stop the current backend before starting the independent automation daemon."
            )
    except httpx.HTTPError:
        pass

    control.parent.mkdir(parents=True, exist_ok=True)
    log_path = control.parent.parent / "logs" / "automation-daemon.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    shutdown_token = secrets.token_urlsafe(32)
    env = {**os.environ, "ATLAS_AUTOMATION_DAEMON": "1", "ATLAS_SHUTDOWN_TOKEN": shutdown_token}
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
    with log_path.open("ab") as log_file:
        process = subprocess.Popen(
            [sys.executable, "-m", "atlas.cli", "serve", "--port", str(selected_port)],
            env=env, cwd=os.getcwd(), stdin=subprocess.DEVNULL,
            stdout=log_file, stderr=log_file, creationflags=flags,
            start_new_session=os.name != "nt",
        )
    deadline = time.time() + 60
    while time.time() < deadline and process.poll() is None:
        try:
            response = _daemon_request("GET", "/api/health", selected_port, timeout=1.0)
            if response.is_success:
                control.write_text(json_module.dumps({"pid": process.pid, "port": selected_port,
                    "shutdown_token": shutdown_token, "started_at": time.time()}, indent=2), encoding="utf-8")
                console.print(f"Automation daemon started (pid={process.pid}, port={selected_port}).")
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise click.ClickException(f"Automation daemon failed to become healthy; see {log_path}")


@daemon.command("status")
def daemon_status() -> None:
    """Show daemon health and active automation count."""
    import json as json_module
    import httpx

    control = _daemon_control_file()
    if not control.is_file():
        console.print("Automation daemon is not running.")
        return
    try:
        info = json_module.loads(control.read_text(encoding="utf-8"))
        health = _daemon_request("GET", "/api/health", int(info["port"]), timeout=2.0)
        response = _daemon_request("GET", "/api/automations", int(info["port"]), timeout=3.0)
        automations = response.json().get("automations", []) if response.is_success else []
        console.print(f"Automation daemon healthy (pid={info['pid']}, port={info['port']}); "
                      f"{sum(bool(item.get('enabled')) for item in automations)} enabled automations.")
        if not health.is_success:
            raise httpx.HTTPError("unhealthy")
    except (OSError, ValueError, KeyError, TypeError, json_module.JSONDecodeError, httpx.HTTPError):
        console.print("Automation daemon control record exists, but its server is not healthy.")


@daemon.command("stop")
def daemon_stop() -> None:
    """Gracefully stop the server and release its DBOS/data locks."""
    import json as json_module
    import time
    import httpx

    control = _daemon_control_file()
    if not control.is_file():
        console.print("Automation daemon is not running.")
        return
    try:
        info = json_module.loads(control.read_text(encoding="utf-8"))
        _daemon_request("POST", "/api/runtime/shutdown", int(info["port"]),
                        token=str(info.get("shutdown_token", "")), timeout=3.0)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                _daemon_request("GET", "/api/health", int(info["port"]), timeout=0.5)
            except httpx.HTTPError:
                break
            time.sleep(0.25)
        else:
            raise click.ClickException("Daemon did not release its server port within 30 seconds")
    except (OSError, ValueError, KeyError, TypeError, json_module.JSONDecodeError) as exc:
        raise click.ClickException(f"Could not stop automation daemon: {exc}") from exc
    control.unlink(missing_ok=True)
    console.print("Automation daemon stopped; DBOS and data locks released.")


@daemon.command("enable-startup")
def daemon_enable_startup() -> None:
    """Start the detached daemon at Windows user login."""
    if os.name != "nt":
        raise click.ClickException("Automatic login startup is currently supported on Windows only.")
    import winreg
    command = f'"{sys.executable}" -m atlas.cli daemon start'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "AtlasAutomationDaemon", 0, winreg.REG_SZ, command)
    console.print("Automation daemon will start at your next Windows login; closing the UI does not stop it.")


@daemon.command("disable-startup")
def daemon_disable_startup() -> None:
    """Remove Atlas's Windows login startup entry without stopping a running daemon."""
    if os.name != "nt":
        raise click.ClickException("Automatic login startup is currently supported on Windows only.")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0,
                        winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, "AtlasAutomationDaemon")
        except FileNotFoundError:
            pass
    console.print("Automation daemon will no longer start at Windows login; any running daemon remains active.")


@main.command()
@click.option("--model", "-m", default=None, help="Model to use")
def chat(model: str | None) -> None:
    """Start an interactive chat session in the terminal."""
    from atlas.agent import AgentOrchestrator
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager

    async def _chat() -> None:
        model_mgr = ModelManager()
        if model:
            model_mgr.select(model)

        memory = MemoryStore()
        await memory.init()
        from atlas.config import DATA_ROOT
        from atlas.engine.session_migration import migrate_legacy_sessions

        migration = await migrate_legacy_sessions(DATA_ROOT / "engine", memory)
        if migration.status != "ready":
            raise RuntimeError(migration.error or "会话迁移失败；历史记录已保护。")

        orch = AgentOrchestrator(model_mgr=model_mgr, memory=memory)

        from atlas.ide_context import discover_ide_context, format_ide_context
        ide_context = await discover_ide_context()

        import uuid
        conv_id = str(uuid.uuid4())

        console.print(f"[bold]Atlas[/bold] v0.1.0 | Model: [cyan]{model_mgr.current_model}[/cyan]")
        console.print("Type [bold]quit[/bold] or [bold]exit[/bold] to leave. "
                      "[bold]/model <id>[/bold] to switch model.\n")
        if ide_context:
            file_hint = f" · 文件 {ide_context['file']}" if ide_context.get("file") else ""
            console.print(f"[dim]已发现 {ide_context.get('editor') or 'IDE'} 上下文：工作区 {ide_context.get('workspace')}{file_hint}；首次提问时附上。[/dim]\n")
        attach_ide_context = bool(ide_context)

        while True:
            try:
                user_input = console.input("[bold green]You:[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\nBye!")
                break

            if not user_input:
                continue

            if user_input.lower() in ("quit", "exit"):
                console.print("Bye!")
                break

            if user_input.startswith("/model "):
                new_model = user_input.split(" ", 1)[1].strip()
                try:
                    model_mgr.select(new_model)
                    console.print(f"Switched to [cyan]{new_model}[/cyan]")
                except ValueError as e:
                    console.print(f"[red]{e}[/red]")
                continue

            if user_input == "/models":
                for m in model_mgr.list_models():
                    star = " *" if m["selected"] else ""
                    fav = " ★" if m["favorite"] else ""
                    console.print(f"  {m['id']}{star}{fav} — {m['name']}")
                continue

            # Save user message and run agent
            await memory.save_conversation_metadata(conv_id, title_hint=user_input)

            if attach_ide_context and ide_context:
                user_input = f"{format_ide_context(ide_context)}\n\nUser request:\n{user_input}"
                attach_ide_context = False

            console.print(f"[bold]{model_mgr.current_model}[/bold] > ", end="")
            full = ""
            run_kwargs: dict[str, Any] = {}
            if ide_context and ide_context.get("workspace"):
                run_kwargs = {"workspace": str(ide_context["workspace"]), "workspace_trusted": True}
            async for event in orch.run(user_input, conv_id, **run_kwargs):
                if event["type"] == "chunk":
                    print(event["content"], end="", flush=True)
                    full += event["content"]
                elif event["type"] == "error":
                    console.print(f"\n[red]Error: {event['detail']}[/red]")
                elif event["type"] == "done":
                    print()  # newline after streaming
            print()  # blank line between turns

        await memory.close()

    asyncio.run(_chat())


@main.command()
def version() -> None:
    """Show Atlas version."""
    console.print("Atlas v0.1.0")


@main.command("config-migrate")
@click.option("--rollback", is_flag=True, help="Restore sanitized pre-v2 config/settings backups")
def config_migrate(rollback: bool) -> None:
    """Show or run the versioned local config migration; credentials remain in the OS keyring."""
    from atlas.config import CONFIG_PATH, USER_SETTINGS_PATH
    from atlas.config_migrations import migrate_configuration, rollback_configuration_migration

    if rollback:
        restored = rollback_configuration_migration(CONFIG_PATH, USER_SETTINGS_PATH)
        console.print(json.dumps({"rollback": restored}, ensure_ascii=False))
        return
    result = migrate_configuration(CONFIG_PATH, USER_SETTINGS_PATH)
    console.print(json.dumps(result, ensure_ascii=False))
    if result.get("config_error") or result.get("settings_error"):
        raise click.ClickException("配置迁移未完成；原文件已保留，请修复系统凭据库后重试。")


@main.command("exec")
@click.argument("prompt", required=False)
@click.option("--model", "-m", default=None, help="Model to use")
@click.option("--workspace", "--cwd", type=click.Path(file_okay=False, path_type=Path), default=".",
              show_default=True, help="Workspace directory for this run")
@click.option("--conversation-id", "--resume", default=None, help="Resume an existing Atlas conversation")
@click.option("--output-format", type=click.Choice(["text", "jsonl"]), default="text",
              show_default=True, help="Stream plain text or one JSON object per event")
@click.option("--json", "json_output", is_flag=True, help="Alias for --output-format jsonl")
@click.option("--output-schema", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Require the final response to match this JSON Schema file")
@click.option("--output-last-message", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Write the final assistant response to this file")
@click.option("--approve-writes", is_flag=True,
              help="Approve write-capable tool calls for this non-interactive run")
@click.option("--project-id", default=None, help="Run within one Atlas project configuration/credential scope")
@click.option("--config-override", type=click.Path(dir_okay=False, path_type=Path), default=None,
              help="Apply a strict temporary JSON config override for this run only")
@click.option("--ignore-project-config", is_flag=True, help="Ignore the selected project's saved config for this run")
@click.option("--ignore-workspace-rules", is_flag=True, help="Skip AGENTS.md / CLAUDE.md workspace instructions for this run")
def exec_command(
    prompt: str | None, model: str | None, workspace: Path,
    conversation_id: str | None, output_format: str, json_output: bool,
    output_schema: Path | None, output_last_message: Path | None, approve_writes: bool,
    project_id: str | None, config_override: Path | None, ignore_project_config: bool,
    ignore_workspace_rules: bool,
) -> None:
    """Run one non-interactive agent turn; PROMPT may also come from stdin."""
    from atlas.agent import AgentOrchestrator
    from atlas.config import DATA_ROOT
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager
    from atlas.project_context import project_scoped_events, validate_config_override

    user_prompt = prompt if prompt is not None else sys.stdin.read()
    user_prompt = user_prompt.strip()
    if not user_prompt:
        raise click.UsageError("PROMPT or non-empty stdin input is required.")
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise click.BadParameter(f"workspace is not a directory: {root}", param_hint="--workspace")
    ide_context: dict[str, Any] | None = None
    try:
        from atlas.ide_context import discover_ide_context

        ide_context = asyncio.run(discover_ide_context(cwd=root))
    except (OSError, RuntimeError, ValueError):
        ide_context = None
    if ide_context:
        if root == Path.cwd().resolve() and ide_context.get("workspace"):
            detected_workspace = Path(str(ide_context["workspace"])).expanduser().resolve()
            if detected_workspace.is_dir():
                root = detected_workspace
        from atlas.ide_context import format_ide_context

        user_prompt = f"{format_ide_context(ide_context)}\n\nUser request:\n{user_prompt}"
        if output_format != "jsonl":
            print(f"IDE context attached ({ide_context.get('editor') or 'IDE'}; workspace {root}).", file=sys.stderr)
    if json_output:
        output_format = "jsonl"
    temporary_config = None
    if config_override:
        try:
            raw_override = json.loads(config_override.read_text(encoding="utf-8"))
            temporary_config = validate_config_override(raw_override)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise click.BadParameter(f"invalid temporary config override: {exc}", param_hint="--config-override") from exc
    schema: dict[str, Any] | None = None
    if output_schema:
        try:
            schema = json.loads(output_schema.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise click.BadParameter(f"cannot read JSON Schema: {exc}", param_hint="--output-schema") from exc

    async def _run_once() -> bool:
        model_mgr = ModelManager()
        if model:
            model_mgr.select(model)
        memory = MemoryStore()
        await memory.init()
        try:
            from atlas.engine.session_migration import migrate_legacy_sessions

            migration = await migrate_legacy_sessions(DATA_ROOT / "engine", memory)
            if migration.status != "ready":
                raise RuntimeError(migration.error or "历史会话尚未完成安全迁移")
            conv_id = conversation_id or str(__import__("uuid").uuid4())
            await memory.save_conversation_metadata(conv_id, title_hint=user_prompt)
            orchestrator = AgentOrchestrator(model_mgr=model_mgr, memory=memory)
            async def approve_once(event_id: str, tool_name: str, arguments: dict[str, Any]) -> str:
                return "allow" if approve_writes else "deny"

            failed = False
            if output_format == "jsonl":
                _write_line({"type": "start", "session_id": conv_id}, sys.stdout)
            final_text = ""
            validation_error = ""
            structured_output: Any = None
            for attempt in range(3):
                parts: list[str] = []
                run_prompt = user_prompt
                if schema is not None:
                    run_prompt += "\n\nReturn only a JSON value that strictly matches this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
                    if attempt:
                        run_prompt += f"\nYour previous response failed schema validation: {validation_error}. Rewrite it now."
                run_events = orchestrator.run(
                    run_prompt, conv_id, workspace=str(root), workspace_trusted=True,
                    permission_mode="ask_writes",
                    project_id=project_id,
                    ignore_workspace_rules=ignore_workspace_rules,
                    approval_callback=approve_once if approve_writes else None,
                )
                async for event in project_scoped_events(
                    project_id, run_events, config_override=temporary_config,
                    ignore_project_config=ignore_project_config,
                    session_id=conv_id,
                ):
                    kind = event.get("type")
                    if kind == "chunk":
                        part = str(event.get("content", "")); parts.append(part)
                        if output_format == "jsonl":
                            _write_line({"type": "text_delta", "text": part}, sys.stdout)
                        else:
                            print(part, end="", flush=True)
                    elif output_format == "jsonl" and kind in {"tool_call", "tool_result", "usage"}:
                        _write_line(event, sys.stdout)
                    if kind == "tool_call":
                        # Text before a tool call is narration ("let me read the file"); the final
                        # answer is what the model says after its last tool call.
                        parts = []
                    elif kind == "error":
                        failed = True
                        print(str(event.get("detail", "Agent run failed")), file=sys.stderr)
                final_text = "".join(parts)
                if failed:
                    break
                if schema is None:
                    break
                try:
                    import jsonschema
                    final_text = _strip_json_fence(final_text)
                    structured_output = json.loads(final_text)
                    jsonschema.validate(structured_output, schema)
                    validation_error = ""
                    break
                except Exception as exc:
                    validation_error = str(exc)
                    if attempt == 2:
                        failed = True
                        print(f"Final response did not match --output-schema: {validation_error}", file=sys.stderr)
            if output_last_message:
                output_last_message.parent.mkdir(parents=True, exist_ok=True)
                output_last_message.write_text(final_text, encoding="utf-8")
            if output_format == "jsonl":
                final_event: dict[str, Any] = {"type": "final", "session_id": conv_id, "text": final_text}
                if schema is not None and not failed:
                    final_event["structured"] = structured_output
                _write_line(final_event, sys.stdout)
                _write_line({"type": "end", "session_id": conv_id, "status": "failed" if failed else "completed"}, sys.stdout)
            elif final_text:
                print()
            return failed
        finally:
            await memory.close()

    try:
        failed = asyncio.run(_run_once())
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    if failed:
        sys.exit(EXIT_RUN_FAILED)


@main.command("app-server")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), default=".",
              show_default=True, help="Default workspace for sessions")
def app_server_command(workspace: Path) -> None:
    """Start the newline-delimited JSON-RPC SDK server on stdin/stdout."""
    from atlas.tools.app_server import serve_stdio

    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise click.BadParameter(f"workspace is not a directory: {root}", param_hint="--workspace")
    try:
        asyncio.run(serve_stdio(workspace=str(root), protocol="app-server"))
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


@main.command("acp")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), default=".",
              show_default=True, help="Default workspace for ACP sessions")
def acp_command(workspace: Path) -> None:
    """Run Atlas as an Agent Client Protocol (ACP) stdio agent."""
    from atlas.tools.app_server import serve_stdio

    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise click.BadParameter(f"workspace is not a directory: {root}", param_hint="--workspace")
    try:
        asyncio.run(serve_stdio(workspace=str(root), protocol="acp"))
    except (OSError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc


def _hub_control_file() -> Any:
    from pathlib import Path

    from atlas.config import get_config

    return Path(get_config().db_path).parent / "hub.json"


def _hub_request(method: str, path: str, port: int, timeout: float = 3.0):
    import httpx

    return httpx.request(method, f"http://127.0.0.1:{port}{path}", timeout=timeout)


@main.group()
def hub() -> None:
    """Run the detached background Hub (scheduler + durable + local agent)."""


@hub.command("start")
@click.option("--port", default=None, type=int, help="Hub port (default 8793)")
def hub_start(port: int | None) -> None:
    """Start the Hub as a detached background process."""
    import json
    import os
    import subprocess
    import sys
    import time

    import httpx


    control = _hub_control_file()
    if control.is_file():
        try:
            info = json.loads(control.read_text(encoding="utf-8"))
            _hub_request("GET", "/health", int(info["port"]), timeout=1.0)
            console.print(f"[yellow]Hub already running on port {info['port']}.[/yellow]")
            return
        except (OSError, httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            control.unlink(missing_ok=True)

    hub_port = port or int(os.environ.get("ATLAS_HUB_PORT", "8793"))
    env = {**os.environ, "ATLAS_HUB_PORT": str(hub_port)}
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [sys.executable, "-m", "atlas.runtime.hub"],
        env=env, creationflags=flags, cwd=os.getcwd(),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            _hub_request("GET", "/health", hub_port, timeout=1.0)
            control.write_text(json.dumps({"pid": process.pid, "port": hub_port}), encoding="utf-8")
            console.print(f"[green]Hub started[/green] pid={process.pid} port={hub_port}")
            return
        except httpx.HTTPError:
            time.sleep(0.5)
    console.print("[red]Hub did not become healthy in time.[/red]")


@hub.command("stop")
def hub_stop() -> None:
    """Stop a running Hub."""
    import json

    import httpx

    control = _hub_control_file()
    if not control.is_file():
        console.print("[yellow]Hub is not running (no control file).[/yellow]")
        return
    info = json.loads(control.read_text(encoding="utf-8"))
    try:
        _hub_request("POST", "/shutdown", int(info["port"]), timeout=3.0)
        console.print("[green]Hub stopped.[/green]")
    except httpx.HTTPError:
        console.print("[yellow]Hub did not answer; it may have already exited.[/yellow]")
    finally:
        control.unlink(missing_ok=True)


@hub.command("status")
def hub_status() -> None:
    """Show Hub health and scheduler status."""
    import json

    import httpx

    control = _hub_control_file()
    if not control.is_file():
        console.print("[yellow]Hub is not running.[/yellow]")
        return
    info = json.loads(control.read_text(encoding="utf-8"))
    try:
        _hub_request("GET", "/health", int(info["port"]), timeout=2.0).json()
        status_body = _hub_request("GET", "/status", int(info["port"]), timeout=2.0).json()
        console.print(f"[green]Hub healthy[/green] port={info['port']} pid={info['pid']}")
        console.print(f"scheduler_running={status_body.get('scheduler_running')} "
                      f"tasks={status_body.get('task_count')}")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        console.print("[red]Hub control file exists but the process is not answering.[/red]")


@hub.command("tasks")
def hub_tasks() -> None:
    """List Hub scheduled tasks."""
    import json

    import httpx

    control = _hub_control_file()
    if not control.is_file():
        console.print("[yellow]Hub is not running.[/yellow]")
        return
    info = json.loads(control.read_text(encoding="utf-8"))
    try:
        body = _hub_request("GET", "/tasks", int(info["port"]), timeout=2.0).json()
        for task in body.get("tasks", []):
            console.print(f"- {task.get('id')}: {task.get('name')} "
                          f"({task.get('trigger_type')} {task.get('trigger_args')})")
        if not body.get("tasks"):
            console.print("(no hub tasks)")
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        console.print("[red]Hub is not answering.[/red]")


def cli_main() -> None:
    """Console entry point: ``main`` plus machine-readable errors on stderr.

    Argument problems (bad option values, missing commands) print one JSON
    error object to stderr and exit 2; other Click-level failures exit 1.
    """
    try:
        main(standalone_mode=False, windows_expand_args=False)
    except click.exceptions.UsageError as exc:
        _error_line("arguments", exc.format_message())
        sys.exit(EXIT_USAGE)
    except click.exceptions.ClickException as exc:
        _error_line("cli", exc.format_message())
        sys.exit(EXIT_RUN_FAILED)
    except click.exceptions.Abort:
        _error_line("cli", "aborted")
        sys.exit(EXIT_RUN_FAILED)


# ---------------------------------------------------------------------------
# H9 headless CLI — `atlas run` / `atlas doctor`
#
# EXPOSE of existing capability only: the runtime is the regular Atlas app
# (`atlas.server:app`, in-process uvicorn thread, or an already-running backend
# via ``--server URL``); a turn is driven through the existing Runtime Event
# Protocol WebSocket (`/ws/chat`), so stream-json lines ARE the WebSocket
# events. No business logic lives here.
# ---------------------------------------------------------------------------

EXIT_OK = 0            # run completed (a client-side max-turns stop also counts as 0)
EXIT_RUN_FAILED = 1    # run failed / cancelled / transport or startup error
EXIT_USAGE = 2         # argument error
EXIT_APPROVAL = 3      # approval (or workspace trust) was needed but nobody could approve

PERMISSION_MODES = ("full_access", "ask_each", "ask_writes", "auto_file", "plan", "read_only")
OUTPUT_FORMATS = ("text", "json", "stream-json")
_TERMINAL_EVENTS = {"run.completed", "run.failed", "run.cancelled"}


def _strip_json_fence(text: str) -> str:
    """Accept a final answer wrapped in a ```json fence: models often add one around the object."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def _error_line(scope: str, detail: str) -> None:
    """Emit one machine-readable JSON error object on stderr."""
    sys.stderr.write(json.dumps(
        {"type": "error", "scope": scope, "detail": detail}, ensure_ascii=False,
    ) + "\n")
    sys.stderr.flush()


def _write_line(payload: dict[str, Any], out: TextIO) -> None:
    out.write(json.dumps(payload, ensure_ascii=False) + "\n")
    out.flush()


class _StdoutGuard:
    """Reserve process stdout for CLI data; engine chatter goes to stderr.

    The headless runtime runs in-process, and the engine prints banners and
    tool traces with plain ``print``/``sys.stdout``. ``atlas run`` output
    formats promise one-parseable-object-per-line stdout, so during a run
    ``sys.stdout`` is redirected to stderr while the CLI writes its data to
    the saved real stdout.
    """

    def __init__(self) -> None:
        self.real_stdout: TextIO = sys.stdout

    def __enter__(self) -> TextIO:
        sys.stdout = sys.stderr
        return self.real_stdout

    def __exit__(self, *_exc: object) -> None:
        sys.stdout = self.real_stdout


def _ws_headers() -> dict[str, str]:
    """Headers for local HTTP/WS clients (OriginGuard: no Origin = local process)."""
    token = os.environ.get("ATLAS_API_TOKEN", "")
    return {"x-atlas-api-token": token} if token else {}


class _HeadlessServer:
    """The regular Atlas app served in-process on an ephemeral loopback port."""

    def __init__(self) -> None:
        import threading
        import time as _time

        import uvicorn

        from atlas import server as atlas_server

        config = uvicorn.Config(
            atlas_server.app, host="127.0.0.1", port=0,
            log_level="warning", lifespan="on",
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, daemon=True, name="atlas-headless",
        )
        self._thread.start()
        deadline = _time.monotonic() + 180
        while not self._server.started:
            if not self._thread.is_alive():
                raise RuntimeError("Atlas 运行时线程在启动阶段退出")
            if _time.monotonic() > deadline:
                self.stop()
                raise RuntimeError("Atlas 运行时 180 秒内未完成启动")
            _time.sleep(0.05)
        socket_ = self._server.servers[0].sockets[0]
        host, port = socket_.getsockname()[:2]
        self.base_url = f"http://{host}:{port}"

    def stop(self) -> None:
        self._server.should_exit = True
        if self._thread.is_alive():
            self._thread.join(timeout=60)


def _normalize_server_url(url: str) -> str:
    base = url.rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    if base.startswith(("ws://", "wss://")):
        return base
    raise ValueError(f"--server 需要 http(s):// 或 ws(s):// 地址，收到：{url}")


async def _ensure_conversation(base_url: str) -> str:
    """Create the conversation through the existing REST seam (like the frontend)."""
    import httpx

    async with httpx.AsyncClient(base_url=base_url, headers=_ws_headers(), timeout=60) as client:
        response = await client.post("/api/conversations", json={"title": "Headless run"})
        if response.status_code != 200:
            raise RuntimeError(f"创建会话失败：HTTP {response.status_code} {response.text[:200]}")
        conversation_id = str(response.json().get("id", ""))
    if not conversation_id:
        raise RuntimeError("创建会话失败：响应缺少会话 id")
    return conversation_id


class _TurnRenderer:
    """Turn stream output for the three --output-format values."""

    def __init__(self, output_format: str, out: TextIO) -> None:
        from rich.console import Console

        self.format = output_format
        self.out = out
        self.console = Console(file=out)
        self._streamed = False

    def envelope(self, envelope: dict[str, Any]) -> None:
        if self.format == "stream-json":
            _write_line(envelope, self.out)
            return
        if self.format != "text":
            return
        event = envelope.get("event", "")
        data = envelope.get("data") or {}
        if event == "message.delta":
            content = data.get("content")
            if isinstance(content, str) and content:
                self.out.write(content)
                self.out.flush()
                self._streamed = True
        elif event == "message.completed":
            content = data.get("content")
            if self._streamed:
                self.out.write("\n")
            elif isinstance(content, str) and content:
                self.out.write(content + "\n")
            self.out.flush()
            self._streamed = False
        elif event == "tool.started":
            name = str(data.get("name", ""))
            if name:
                if self._streamed:
                    self.out.write("\n")
                    self.out.flush()
                    self._streamed = False
                self.console.print(f"[dim]→ tool {name}[/dim]")

    def notice(self, text: str) -> None:
        """Diagnostics that must never corrupt a parsed stdout stream."""
        if self.format == "text":
            self.console.print(f"[yellow]{text}[/yellow]")
        else:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()

    def summary(self, summary: dict[str, Any]) -> None:
        if self.format == "stream-json":
            _write_line(summary, self.out)
        elif self.format == "json":
            self.out.write(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
            self.out.flush()
        else:
            changes = summary.get("changes") or {}
            usage = summary.get("usage") or {}
            by_purpose = usage.get("purpose_totals") or {}
            purpose_text = ",".join(
                f"{purpose}:{values.get('request_count')}"
                for purpose, values in by_purpose.items()
            )
            self.console.print(
                f"result={summary.get('result')} stop_reason={summary.get('stop_reason')} "
                f"conversation={summary.get('conversation_id')} "
                f"files={changes.get('files', 0)} "
                f"(+{changes.get('additions', 0)}/-{changes.get('deletions', 0)}) "
                f"elapsed={summary.get('elapsed_seconds')}s "
                f"tokens(in/out/cache)={usage.get('input_tokens')}/{usage.get('output_tokens')}"
                f"/{usage.get('cached_input_tokens')} requests={usage.get('request_count')} "
                f"purposes={purpose_text}"
            )


async def _drive_turn(
    base_url: str,
    *,
    prompt: str,
    attachments: list[dict[str, str]] | None = None,
    workspace: str,
    model: str | None,
    permission_mode: str | None,
    conversation_id: str,
    max_turns: int | None,
    output_format: str,
    timeout: float,
    out: TextIO,
) -> tuple[int, dict[str, Any]]:
    """One headless turn over the existing /ws/chat Runtime Event Protocol."""
    import uuid

    from websockets.asyncio.client import connect

    from atlas.usage import aggregate_run_usage

    run_id = uuid.uuid4().hex
    renderer = _TurnRenderer(output_format, out)
    started = time.monotonic()
    approvals_denied = 0
    trust_denied = False
    plan_denied = False
    usage_events = 0
    usage_rows: list[dict[str, Any]] = []
    usage_request_ids: set[str] = set()
    stop_reason = ""
    result = ""
    detail = ""
    usage: dict[str, Any] = {}
    changes: dict[str, Any] = {}
    final_message = ""
    cancel_sent = False

    start_message: dict[str, Any] = {
        "type": "run.start", "run_id": run_id, "content": prompt,
        "conversation_id": conversation_id, "workspace": workspace,
    }
    if attachments:
        start_message["files"] = attachments
    if model:
        start_message["model"] = model
    if permission_mode:
        start_message["permission_mode"] = permission_mode

    async with connect(
        base_url.replace("http", "ws", 1) + "/ws/chat",
        additional_headers=_ws_headers(), max_size=8_000_000,
    ) as ws:
        await ws.send(json.dumps(start_message, ensure_ascii=False))
        deadline = time.monotonic() + timeout

        async def _send(payload: dict[str, Any]) -> None:
            await ws.send(json.dumps(payload, ensure_ascii=False))

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                result, detail, stop_reason = "timeout", "整体超时", "timeout"
                break
            try:
                raw = json.loads(await asyncio.wait_for(ws.recv(), timeout=remaining))
            except TimeoutError:
                result, detail, stop_reason = "timeout", "整体超时", "timeout"
                break
            if not isinstance(raw, dict):
                continue
            msg_type = raw.get("type", "")
            if msg_type == "error":
                result = "failed"
                detail = str(raw.get("detail", "未知错误"))
                break
            if msg_type != "agent_event":
                continue
            event = str(raw.get("event", ""))
            data = raw.get("data") or {}
            renderer.envelope(raw)

            if event == "approval.required":
                # Non-interactive: nobody can approve, so per the taskbook the
                # request is treated as rejected and the run keeps going.
                approvals_denied += 1
                renderer.notice(
                    f"approval: {data.get('tool', '')} 需要审批；非交互模式已自动拒绝"
                    f"（退出码将取 {EXIT_APPROVAL}）"
                )
                await _send({"type": "approval.response",
                             "event_id": data.get("approval_id", ""), "choice": "deny"})
            elif event == "rules.trust_required":
                trust_denied = True
                renderer.notice(
                    "trust: 工作区规则目录未被信任；非交互模式拒绝信任"
                    f"（退出码将取 {EXIT_APPROVAL}）"
                )
                await _send({"type": "rules.trust", "run_id": run_id, "trust": False})
            elif event == "run.plan.proposed":
                # Non-interactive: nobody can approve the proposed plan, so per
                # the taskbook the proposal is treated as rejected. The run is
                # parked server-side (run_drive waits on plan_future, polling
                # cancel_event), so `run.cancel` is the sanctioned way to end it:
                # the backend emits a clean run.cancelled instead of this CLI
                # sitting silent until --timeout (the scenario-08 live hang).
                plan_denied = True
                stop_reason = "plan_needs_approval"
                renderer.notice(
                    "plan: 已收到计划（run.plan.proposed）；非交互模式无人审批，"
                    f"按拒绝处理并结束本轮（退出码将取 {EXIT_APPROVAL}）"
                )
                await _send({"type": "run.cancel", "run_id": run_id})
            elif event == "run.usage":
                if isinstance(data, dict):
                    row = dict(data)
                    usage_rows.append(row)
                    request_id = str(row.get("request_id") or "")
                    if not request_id or request_id not in usage_request_ids:
                        usage_events += 1
                        if request_id:
                            usage_request_ids.add(request_id)
                    usage = aggregate_run_usage(usage_rows)
                if max_turns is not None and usage_events >= max_turns and not cancel_sent:
                    cancel_sent = True
                    stop_reason = "max_turns"
                    renderer.notice(f"limit: 已到 --max-turns {max_turns}，请求取消本轮")
                    await _send({"type": "run.cancel", "run_id": run_id})
            elif event == "message.completed":
                content = data.get("content")
                if isinstance(content, str):
                    final_message = content
            elif event == "run.completed":
                result = "completed"
                if usage_rows:
                    usage = aggregate_run_usage(usage_rows)
                elif isinstance(data.get("usage"), dict):
                    usage = data["usage"]
                if isinstance(data.get("changes"), dict):
                    changes = data["changes"]
                break
            elif event == "run.failed":
                result = "failed"
                detail = str(data.get("detail", ""))
                if usage_rows:
                    usage = aggregate_run_usage(usage_rows)
                elif isinstance(data.get("usage"), dict):
                    usage = data["usage"]
                break
            elif event in ("run.cancelled",):
                result = "cancelled"
                break
            elif event in _TERMINAL_EVENTS:  # pragma: no cover — covered above
                result = "failed"
                break

    elapsed = round(time.monotonic() - started, 3)
    if not result:
        result, detail = "failed", "事件流在结束前关闭"
    summary = {
        "type": "summary",
        "result": result,
        "run_id": run_id,
        "conversation_id": conversation_id,
        "stop_reason": stop_reason or result,
        "elapsed_seconds": elapsed,
        "usage": usage,
        "changes": changes,
        "approvals_denied": approvals_denied,
        "trust_denied": trust_denied,
        "plan_denied": plan_denied,
        "message": final_message,
    }
    if detail:
        summary["detail"] = detail
    renderer.summary(summary)
    if result == "failed":
        _error_line("run", detail or "run failed")
    elif result == "timeout":
        _error_line("run", f"turn exceeded --timeout {timeout}s")
    elif result == "cancelled" and stop_reason not in ("max_turns", "plan_needs_approval"):
        _error_line("run", "run was cancelled")

    if approvals_denied or trust_denied or (plan_denied and result == "cancelled"):
        return EXIT_APPROVAL, summary
    if result == "completed" or (result == "cancelled" and stop_reason == "max_turns"):
        return EXIT_OK, summary
    return EXIT_RUN_FAILED, summary


async def _run_headless(
    *,
    prompt: str,
    attachments: list[dict[str, str]],
    workspace: str,
    model: str | None,
    permission_mode: str | None,
    conversation_id: str | None,
    output_format: str,
    max_turns: int | None,
    server_url: str | None,
    timeout: float,
    out: TextIO,
) -> int:
    import httpx
    from websockets import exceptions as websockets_exceptions

    headless: _HeadlessServer | None = None
    try:
        if server_url:
            try:
                base_url = _normalize_server_url(server_url).replace("ws", "http", 1)
            except ValueError as exc:
                _error_line("arguments", str(exc))
                return EXIT_USAGE
        else:
            try:
                headless = _HeadlessServer()
            except (ImportError, OSError, RuntimeError) as exc:
                _error_line("server", f"内置运行时启动失败：{exc}")
                return EXIT_RUN_FAILED
            base_url = headless.base_url
        try:
            conv_id = conversation_id or await _ensure_conversation(base_url)
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            _error_line("server", str(exc))
            return EXIT_RUN_FAILED
        try:
            exit_code, _summary = await _drive_turn(
                base_url,
                prompt=prompt, workspace=workspace, model=model,
                attachments=attachments,
                permission_mode=permission_mode, conversation_id=conv_id,
                max_turns=max_turns, output_format=output_format, timeout=timeout,
                out=out,
            )
        except (OSError, ValueError, websockets_exceptions.WebSocketException) as exc:
            _error_line("server", f"运行时通信失败 {base_url}：{exc}")
            return EXIT_RUN_FAILED
        return exit_code
    finally:
        if headless is not None:
            headless.stop()


def _validate_run_arguments(workspace: Path, max_turns: int | None, timeout: float) -> str | None:
    if not workspace.is_absolute():
        return f"工作区必须是绝对路径：{workspace}"
    if not workspace.is_dir():
        return f"工作区目录不存在：{workspace}"
    if max_turns is not None and max_turns < 1:
        return f"--max-turns 必须 >= 1，收到：{max_turns}"
    if timeout <= 0:
        return f"--timeout 必须 > 0，收到：{timeout}"
    return None


@main.command()
@click.option("--print", "-p", "prompt_text", default=None,
              help="本轮任务描述；缺省时从 stdin 读取")
@click.option("--attach", "attachments", multiple=True, type=click.Path(path_type=Path, exists=True, dir_okay=False),
              help="附加文件到首条消息（可重复指定；总大小最多 5 MiB）")
@click.option("--workspace", default=None, help="工作目录（默认当前目录，须为绝对路径）")
@click.option("--model", "-m", default=None, help="模型 ID（默认用配置的默认模型）")
@click.option("--permission-mode", "permission_mode", default=None,
              type=click.Choice(PERMISSION_MODES), help="本轮权限模式（默认 full_access）")
@click.option("--output-format", "output_format", default="text",
              type=click.Choice(OUTPUT_FORMATS), help="输出格式（默认 text）")
@click.option("--max-turns", "max_turns", default=None, type=int,
              help="最多模型请求轮数，达到即取消（不填为不限）")
@click.option("--resume", "resume_id", default=None, help="继续既有会话的 conversation id")
@click.option("--server", "server_url", default=None,
              help="连接已运行的后端 URL（默认进程内直接启动运行时）")
@click.option("--timeout", default=1800.0, show_default=True, help="单轮整体超时秒数")
def run(prompt_text: str | None, attachments: tuple[Path, ...], workspace: str | None, model: str | None,
        permission_mode: str | None, output_format: str, max_turns: int | None,
        resume_id: str | None, server_url: str | None, timeout: float) -> None:
    """Headless one-shot run: start the Atlas runtime and serve one task.

    Exit codes: 0 成功；1 运行失败；2 参数错误；3 非交互模式下需要审批（按拒绝处理）。
    """
    prompt = prompt_text
    if prompt is None and not sys.stdin.isatty():
        prompt = sys.stdin.read()
    if not prompt or not prompt.strip():
        _error_line("arguments", "缺少任务：用 -p \"<任务>\" 或通过 stdin 传入")
        sys.exit(EXIT_USAGE)

    workspace_path = Path(workspace or os.getcwd()).expanduser().resolve()
    problem = _validate_run_arguments(workspace_path, max_turns, timeout)
    if problem:
        _error_line("arguments", problem)
        sys.exit(EXIT_USAGE)

    attached_files: list[dict[str, str]] = []
    attached_bytes = 0
    try:
        for path in attachments:
            resolved = path.expanduser().resolve(strict=True)
            raw = resolved.read_bytes()
            attached_bytes += len(raw)
            if attached_bytes > _CLI_ATTACH_MAX_BYTES:
                raise ValueError("附件合计超过 5 MiB（Base64 后需要通过运行协议传输）")
            attached_files.append({
                "name": resolved.name,
                "mime": mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
                "data_base64": base64.b64encode(raw).decode("ascii"),
            })
    except (OSError, ValueError) as exc:
        _error_line("arguments", f"无法读取 --attach 文件：{exc}")
        sys.exit(EXIT_USAGE)

    # In-process mode: the engine prints via sys.stdout, so reserve the real
    # stdout for CLI data (--server mode has no engine in this process).
    if server_url:
        out: TextIO = sys.stdout
    else:
        guard = _StdoutGuard()
        out = guard.__enter__()
    try:
        exit_code = asyncio.run(_run_headless(
            prompt=prompt,
            attachments=attached_files,
            workspace=str(workspace_path),
            model=model,
            permission_mode=permission_mode,
            conversation_id=resume_id,
            output_format=output_format,
            max_turns=max_turns,
            server_url=server_url,
            timeout=timeout,
            out=out,
        ))
    finally:
        if not server_url:
            guard.__exit__()
    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# `atlas doctor` — config / sessions / model connectivity / MCP status
# ---------------------------------------------------------------------------

def _check_config() -> dict[str, Any]:
    from atlas.config import DATA_ROOT, load_config

    cfg = load_config()
    db_path = cfg.db_path
    db_ok = True
    db_detail = ""
    db_exists = db_path.exists()
    if db_exists:
        try:
            import sqlite3

            # Read-only probe: a diagnostics command must not create the DB.
            with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
                conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except (OSError, sqlite3.Error) as exc:
            db_ok = False
            db_detail = str(exc)
    return {
        "ok": db_ok,
        "config_path": str(DATA_ROOT / "config" / "atlas.toml"),
        "data_root": str(DATA_ROOT),
        "db_path": str(db_path),
        "db_exists": db_exists,
        "db_error": db_detail,
        "scheduler_enabled": cfg.scheduler_enabled,
        "default_model": cfg.default_model,
    }


def _check_sessions() -> dict[str, Any]:
    """Read-only audit of transcript ownership, counts and tool-call pairing."""
    import sqlite3
    from contextlib import closing

    from atlas.config import DATA_ROOT, get_config

    atlas_db = get_config().db_path
    # The engine home is always <data>/engine (HermesRuntime pins it); a user-level
    # HERMES_HOME belongs to a standalone Hermes install and must not be audited here.
    hermes_home = DATA_ROOT / "engine"
    state_db = hermes_home / "state.db"
    metadata_ids: set[str] = set()
    atlas_ids: set[str] = set()
    conversations_total = 0
    atlas_message_count = 0
    db_error = ""
    if atlas_db.exists():
        try:
            with closing(sqlite3.connect(f"file:{atlas_db.as_posix()}?mode=ro", uri=True)) as conn:
                # A fresh store may not have its tables yet: that counts as empty.
                tables = {
                    str(row[0]) for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "conversations" in tables:
                    conversations_total = conn.execute(
                        "SELECT count(*) FROM conversations").fetchone()[0]
                    metadata_ids = {
                        str(row[0]) for row in conn.execute("SELECT id FROM conversations")
                    }
                if "messages" in tables:
                    atlas_message_count = int(conn.execute("SELECT count(*) FROM messages").fetchone()[0])
                    atlas_ids = {
                        str(row[0]) for row in conn.execute(
                            "SELECT DISTINCT conversation_id FROM messages")
                    }
        except sqlite3.Error as exc:
            db_error = str(exc)
    hermes_ids: set[str] = set()
    atlas_session_ids: set[str] = set()
    hermes_message_count = 0
    count_mismatches: list[str] = []
    orphan_tool_results = 0
    state_error = ""
    if state_db.exists():
        try:
            with closing(sqlite3.connect(f"file:{state_db.as_posix()}?mode=ro", uri=True)) as conn:
                tables = {
                    str(row[0]) for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'")
                }
                if "sessions" in tables:
                    session_rows = conn.execute("SELECT id, source, message_count FROM sessions").fetchall()
                    hermes_ids = {str(row[0]) for row in session_rows}
                    atlas_sources = {"api_server", "cli", "channel", "telegram", "atlas_import", "atlas", "hub"}
                    atlas_session_ids = {
                        str(row[0]) for row in session_rows if str(row[1] or "") in atlas_sources
                    }
                    active_counts = {
                        str(row[0]): int(row[1]) for row in conn.execute(
                            "SELECT session_id, count(*) FROM messages WHERE active=1 GROUP BY session_id"
                        )
                    } if "messages" in tables else {}
                    if "messages" in tables:
                        messages = conn.execute(
                            "SELECT session_id, role, tool_calls, tool_call_id FROM messages WHERE active=1"
                        ).fetchall()
                        hermes_message_count = len(messages)
                        calls_by_session: dict[str, set[str]] = {}
                        for row in messages:
                            if row[1] != "assistant" or not row[2]:
                                continue
                            try:
                                calls = json.loads(row[2]) if isinstance(row[2], str) else row[2]
                            except (TypeError, ValueError):
                                calls = []
                            for call in calls if isinstance(calls, list) else []:
                                call_id = call.get("id") if isinstance(call, dict) else None
                                if call_id:
                                    calls_by_session.setdefault(str(row[0]), set()).add(str(call_id))
                        orphan_tool_results = sum(
                            1 for row in messages if row[1] == "tool" and row[3]
                            and str(row[3]) not in calls_by_session.get(str(row[0]), set())
                        )
                    count_mismatches = sorted(
                        str(row[0]) for row in session_rows
                        if int(row[2] or 0) != active_counts.get(str(row[0]), 0)
                    )
                else:
                    atlas_session_ids = set()
        except sqlite3.Error as exc:
            state_error = str(exc)
    # A metadata-only conversation with no transcript is valid. Require SessionDB only
    # for Atlas conversations whose legacy message rows prove that history exists.
    # Legacy rows remain read-only for one release, including rows whose metadata
    # was intentionally deleted. Only live metadata conversations require a session.
    missing = sorted((atlas_ids & metadata_ids) - hermes_ids)
    orphans = sorted((hermes_ids - metadata_ids) & atlas_session_ids)
    ok = not missing and not orphans and not count_mismatches and not orphan_tool_results and not db_error and not state_error
    return {
        "ok": ok,
        "atlas_db": str(atlas_db),
        "conversations_total": conversations_total,
        "conversations_with_messages": len(atlas_ids),
        "atlas_legacy_messages": atlas_message_count,
        "hermes_home": str(hermes_home),
        "hermes_sessions": len(hermes_ids),
        "hermes_messages": hermes_message_count,
        "session_message_count_mismatches": count_mismatches,
        "unpaired_tool_results": orphan_tool_results,
        "missing_in_hermes": missing,
        "orphans_in_hermes": orphans,
        "transcript_owner": "SessionDB",
        "legacy_rows_policy": "保留旧 Atlas 消息行只读；同 ID 的现存 SessionDB 历史具有权威性。",
        "atlas_db_error": db_error,
        "state_db_error": state_error,
    }


def _check_models() -> dict[str, Any]:
    """Probe the configured gateway with a models listing (key never printed)."""
    import httpx

    from atlas.config import get_config

    cfg = get_config()
    base_url = cfg.gateway_base_url.rstrip("/")
    api_key = cfg.gateway_api_key
    detail: dict[str, Any] = {
        "gateway_base_url": base_url,
        "default_model": cfg.default_model,
        "api_key_configured": bool(api_key),
    }
    try:
        response = httpx.get(
            base_url + "/models",
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
            timeout=8.0,
        )
        detail["http_status"] = response.status_code
        detail["ok"] = response.status_code == 200
        if response.status_code != 200:
            detail["error"] = f"网关返回 HTTP {response.status_code}"
    except httpx.HTTPError as exc:
        detail["ok"] = False
        detail["error"] = f"网关不可达：{exc}"
    return detail


def _check_mcp() -> dict[str, Any]:
    """Configured MCP servers and node runtime state (no server is started)."""
    try:
        from atlas.tools.mcp_client import MCPClient

        status = MCPClient().get_runtime_status()
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        return {"ok": False, "error": f"MCP 状态查询失败：{exc}", "servers": []}
    return {
        "ok": bool(status.get("available")),
        "node_required": status.get("node_required"),
        "blocking_reason": status.get("blocking_reason"),
        "servers": status.get("servers", []),
    }


@main.command()
@click.argument("check", required=False, type=click.Choice(["sessions"]))
@click.option("--json", "as_json", is_flag=True, help="输出机器可读 JSON")
def doctor(as_json: bool, check: str | None) -> None:
    """Diagnose config, sessions, model connectivity and MCP status.

    Exit codes: 0 全部检查通过；1 存在未通过的检查。
    """
    checks = {"sessions": _check_sessions()} if check == "sessions" else {
        "config": _check_config(), "sessions": _check_sessions(),
        "models": _check_models(), "mcp": _check_mcp(),
    }
    all_ok = all(item.get("ok") is True for item in checks.values())
    if as_json:
        _write_line({"type": "doctor", "ok": all_ok, "checks": checks}, sys.stdout)
    else:
        for name, detail in checks.items():
            mark = "[green]ok[/green]" if detail.get("ok") else "[red]fail[/red]"
            console.print(f"{mark} {name}")
            for key, value in detail.items():
                if key == "ok":
                    continue
                console.print(f"  {key}: {value}")
    sys.exit(EXIT_OK if all_ok else EXIT_RUN_FAILED)



@main.group("remote")
def remote_group() -> None:
    """Open or close a short-lived mobile session to this Atlas machine."""


@remote_group.command("start")
@click.option("--host", default=None, help="Address phones use to reach this machine (default: detected LAN address)")
@click.option("--ttl-hours", type=click.IntRange(1, 24), default=8, show_default=True)
@click.option("--port", type=click.IntRange(1, 65535), default=None, help="Atlas API port")
def remote_start(host: str | None, ttl_hours: int, port: int | None) -> None:
    """Start the local API if needed and print a temporary mobile URL."""
    import httpx
    import subprocess
    import time
    from atlas.config import get_config
    from atlas.remote_access import local_network_address

    selected_port = port or get_config().server_port
    base = f"http://127.0.0.1:{selected_port}"
    try:
        response = httpx.get(f"{base}/api/health", timeout=1.0)
        response.raise_for_status()
    except httpx.HTTPError:
        flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0
        out = open(os.devnull, "ab")
        subprocess.Popen([sys.executable, "-m", "atlas.cli", "serve", "--port", str(selected_port)],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out,
                         creationflags=flags, start_new_session=os.name != "nt")
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                if httpx.get(f"{base}/api/health", timeout=1.0).is_success:
                    break
            except httpx.HTTPError:
                time.sleep(0.4)
        else:
            raise click.ClickException("Atlas 服务启动失败；运行 atlas serve 查看详细错误。")
    try:
        grant = httpx.post(f"{base}/api/remote/access", json={
            "host": host or local_network_address(), "ttl_seconds": ttl_hours * 3600,
        }, timeout=5.0).json()
    except (httpx.HTTPError, ValueError) as exc:
        raise click.ClickException(f"远程入口启动失败：{exc}") from exc
    if not grant.get("url"):
        raise click.ClickException("Atlas 未能创建远程访问链接。")
    console.print(f"Remote URL (valid {ttl_hours}h): {grant['url']}")
    console.print("在同一网络的手机浏览器打开链接；运行 atlas remote stop 可立即撤销。")


@remote_group.command("status")
@click.option("--port", type=click.IntRange(1, 65535), default=None, help="Atlas API port")
def remote_status(port: int | None) -> None:
    """Show remote access state or the last connection error."""
    import httpx
    from atlas.config import get_config

    selected_port = port or get_config().server_port
    try:
        response = httpx.get(f"http://127.0.0.1:{selected_port}/api/remote/status", timeout=3.0)
        response.raise_for_status()
        state = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        console.print(f"Remote access unavailable: {exc}; retry after checking Atlas service.")
        raise click.ClickException("无法连接 Atlas 远程入口") from exc
    console.print(f"Remote access: {state['active_sessions']} active session(s); LAN address {state['host']}; "
                  f"latest expiry {state['latest_expiry'] or 'none'}.")


@remote_group.command("stop")
@click.option("--port", type=click.IntRange(1, 65535), default=None, help="Atlas API port")
def remote_stop(port: int | None) -> None:
    """Revoke every outstanding temporary mobile session."""
    import httpx
    from atlas.config import get_config

    selected_port = port or get_config().server_port
    try:
        response = httpx.post(f"http://127.0.0.1:{selected_port}/api/remote/stop", json={}, timeout=3.0)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        console.print(f"Remote access stop failed: {exc}; retry after checking Atlas service.")
        raise click.ClickException("无法连接 Atlas 远程入口") from exc
    console.print(f"Remote access stopped; revoked {response.json().get('revoked', 0)} session(s).")


@main.group("github")
def github_group() -> None:
    """Preview and install GitHub repository integrations."""


@github_group.command("install-workflow")
@click.option("--workspace", type=click.Path(exists=True, file_okay=False, path_type=Path), default=Path.cwd())
@click.option("--template", "template_name", type=click.Choice(["atlas-review", "python-checks"]), required=True)
@click.option("--overwrite", is_flag=True, help="确认后替换已有目标文件")
@click.option("--yes", is_flag=True, help="非交互安装；仍会打印完整预览")
def github_install_workflow(workspace: Path, template_name: str, overwrite: bool, yes: bool) -> None:
    """Show the selected workflow and required GitHub permissions before installation."""
    from atlas.github_workflows import install_workflow, workflow_preview
    try:
        preview = workflow_preview(workspace, template_name)
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"模板：{preview['label']}\n目标：{preview['destination']}\n所需 GitHub Actions 权限：{preview['permissions']}\n所需 Secrets：{preview['secret']}")
    if preview["exists"]:
        click.echo("目标文件已存在，安装会替换整个文件。当前文件预览：\n" + str(preview["existing_content"]))
        if not overwrite:
            raise click.ClickException("目标文件已存在；检查现有内容后显式使用 --overwrite。")
    click.echo("\n即将写入的 workflow：\n" + str(preview["content"]))
    if not yes and not click.confirm("确认安装这个 workflow？", default=False):
        click.echo("已取消，未写入文件。")
        return
    try:
        path = install_workflow(workspace, template_name, overwrite=overwrite)
    except (OSError, ValueError, FileExistsError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"已安装：{path}\nGitHub 端还需在仓库 Settings → Secrets and variables → Actions 配置上方列出的 secret（如有）。")

if __name__ == "__main__":
    cli_main()
