"""Atlas CLI — command-line entry point."""

import asyncio
import json
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


console = _LazyConsole()


@click.group()
def main() -> None:
    """Atlas — All-in-one AI Personal Assistant."""
    pass


@main.command()
@click.option("--port", default=None, type=int, help="Server port (default: from config)")
@click.option("--reload", is_flag=True, help="Enable auto-reload")
def serve(port: int | None, reload: bool) -> None:
    """Start the Atlas backend server."""
    import uvicorn

    from atlas.config import get_config

    cfg = get_config()
    actual_port = port or cfg.server_port
    host = cfg.server_host

    console.print(f"[bold]Atlas[/bold] server starting on {host}:{actual_port}...")
    uvicorn.run(
        "atlas.server:app",
        host=host,
        port=actual_port,
        reload=reload,
    )


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

        import uuid
        conv_id = str(uuid.uuid4())

        console.print(f"[bold]Atlas[/bold] v0.1.0 | Model: [cyan]{model_mgr.current_model}[/cyan]")
        console.print("Type [bold]quit[/bold] or [bold]exit[/bold] to leave. "
                      "[bold]/model <id>[/bold] to switch model.\n")

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

            console.print(f"[bold]{model_mgr.current_model}[/bold] > ", end="")
            full = ""
            async for event in orch.run(user_input, conv_id):
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


@main.command("exec")
@click.argument("prompt", required=False)
@click.option("--model", "-m", default=None, help="Model to use")
@click.option("--workspace", type=click.Path(file_okay=False, path_type=Path), default=".",
              show_default=True, help="Workspace directory for this run")
@click.option("--conversation-id", default=None, help="Resume an existing Atlas conversation")
@click.option("--output-format", type=click.Choice(["text", "jsonl"]), default="text",
              show_default=True, help="Stream plain text or one JSON object per event")
@click.option("--approve-writes", is_flag=True,
              help="Approve write-capable tool calls for this non-interactive run")
def exec_command(
    prompt: str | None, model: str | None, workspace: Path,
    conversation_id: str | None, output_format: str, approve_writes: bool,
) -> None:
    """Run one non-interactive agent turn; PROMPT may also come from stdin."""
    from atlas.agent import AgentOrchestrator
    from atlas.config import DATA_ROOT
    from atlas.memory import MemoryStore
    from atlas.models import ModelManager

    user_prompt = prompt if prompt is not None else sys.stdin.read()
    user_prompt = user_prompt.strip()
    if not user_prompt:
        raise click.UsageError("PROMPT or non-empty stdin input is required.")
    root = workspace.expanduser().resolve()
    if not root.is_dir():
        raise click.BadParameter(f"workspace is not a directory: {root}", param_hint="--workspace")

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
            async for event in orchestrator.run(
                user_prompt, conv_id, workspace=str(root), workspace_trusted=True,
                permission_mode="ask_writes",
                approval_callback=approve_once if approve_writes else None,
            ):
                if output_format == "jsonl":
                    _write_line(event, sys.stdout)
                elif event.get("type") == "chunk":
                    print(str(event.get("content", "")), end="", flush=True)
                elif event.get("type") == "error":
                    failed = True
                    print(str(event.get("detail", "Agent run failed")), file=sys.stderr)
            if output_format == "text":
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
        asyncio.run(serve_stdio(workspace=str(root)))
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
        asyncio.run(serve_stdio(workspace=str(root)))
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
def run(prompt_text: str | None, workspace: str | None, model: str | None,
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


if __name__ == "__main__":
    cli_main()
