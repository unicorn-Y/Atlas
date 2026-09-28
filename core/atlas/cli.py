"""Atlas CLI — command-line entry point."""

import asyncio
from typing import Any

import click
from rich.console import Console

console = Console()


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
            await memory.save_message(conv_id, "user", user_input)

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


if __name__ == "__main__":
    main()


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
@click.option("--port", default=None, type=int, help="Hub port (default 8791)")
def hub_start(port: int | None) -> None:
    """Start the Hub as a detached background process."""
    import json
    import os
    import subprocess
    import sys
    import time


    control = _hub_control_file()
    if control.is_file():
        try:
            info = json.loads(control.read_text(encoding="utf-8"))
            _hub_request("GET", "/health", int(info["port"]), timeout=1.0)
            console.print(f"[yellow]Hub already running on port {info['port']}.[/yellow]")
            return
        except Exception:
            control.unlink(missing_ok=True)

    hub_port = port or int(os.environ.get("ATLAS_HUB_PORT", "8791"))
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
        except Exception:
            time.sleep(0.5)
    console.print("[red]Hub did not become healthy in time.[/red]")


@hub.command("stop")
def hub_stop() -> None:
    """Stop a running Hub."""
    import json

    control = _hub_control_file()
    if not control.is_file():
        console.print("[yellow]Hub is not running (no control file).[/yellow]")
        return
    info = json.loads(control.read_text(encoding="utf-8"))
    try:
        _hub_request("POST", "/shutdown", int(info["port"]), timeout=3.0)
        console.print("[green]Hub stopped.[/green]")
    except Exception:
        console.print("[yellow]Hub did not answer; it may have already exited.[/yellow]")
    finally:
        control.unlink(missing_ok=True)


@hub.command("status")
def hub_status() -> None:
    """Show Hub health and scheduler status."""
    import json

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
    except Exception:
        console.print("[red]Hub control file exists but the process is not answering.[/red]")


@hub.command("tasks")
def hub_tasks() -> None:
    """List Hub scheduled tasks."""
    import json

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
    except Exception:
        console.print("[red]Hub is not answering.[/red]")
