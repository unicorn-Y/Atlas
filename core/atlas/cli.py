"""Atlas CLI — command-line entry point."""

import asyncio

import click
from rich.console import Console
from rich.markdown import Markdown

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
    from atlas.models import ModelManager
    from atlas.memory import MemoryStore
    from atlas.agent import AgentOrchestrator

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
