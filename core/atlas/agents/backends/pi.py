"""Pi RPC backend entry point."""

import shutil
from pathlib import Path

from atlas.runtime.external_process import ExternalProcessAdapter
from atlas.tools.node_runtime import resolve_node_runtime


def create() -> ExternalProcessAdapter:
    root = Path(__file__).resolve().parents[4]
    cli = root / "node_modules" / "@mariozechner" / "pi-coding-agent" / "dist" / "cli.js"
    runtime = resolve_node_runtime()
    if runtime.executable and cli.is_file():
        return ExternalProcessAdapter(
            "pi", str(runtime.executable),
            [str(cli), "--mode", "rpc", "--no-session"], protocol="pi-rpc",
        )
    if runtime.executable and runtime.npx_script:
        return ExternalProcessAdapter(
            "pi", str(runtime.executable),
            [
                str(runtime.npx_script), "--yes", "@mariozechner/pi-coding-agent@0.73.1",
                "--mode", "rpc", "--no-session",
            ],
            protocol="pi-rpc",
        )
    npx = shutil.which("npx")
    if npx:
        return ExternalProcessAdapter(
            "pi", npx,
            ["--yes", "@mariozechner/pi-coding-agent@0.73.1", "--mode", "rpc", "--no-session"],
            protocol="pi-rpc",
        )
    return ExternalProcessAdapter(
        "pi", "node", [str(cli), "--mode", "rpc", "--no-session"], protocol="pi-rpc"
    )
