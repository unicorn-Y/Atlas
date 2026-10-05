"""Build the data root for the real-model live scenarios (core/tests/live, -m live).

Reads the Atlas config of this checkout (``config/atlas.toml``) READ-ONLY and writes a
throwaway live root (default: ``%TEMP%/atlas-live-root``) with:

- the same gateway, default model and custom model entries (prefixed ``litellm_model``
  kept verbatim, as on the real install);
- engine ``context_length: 65536`` so scenario 06 forces a real auto-compaction;
- ``compression_model`` = the default model, so the compressor summary call goes
  through the real relay;
- a stdio MCP filesystem server (scenario 11) sandboxed to ``<root>/mcp-vault``;
- ``default_workspace`` for the channel gateway (scenario 12).

The API key is copied into the live root only; it is never printed.

Then run (from core/):
    set ATLAS_LIVE=1
    set ATLAS_LIVE_SMOKE_ROOT=<printed live_root>
    .venv\\Scripts\\python -m pytest tests/test_live_full_run.py tests/test_live_full_run_server.py -m live
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FS_SERVER = REPO / "core" / "tests" / "live" / "11-mcp-filesystem" / "mcp_fs_server.mjs"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=REPO / "config" / "atlas.toml")
    parser.add_argument("--root", type=Path,
                        default=Path(tempfile.gettempdir()) / "atlas-live-root")
    args = parser.parse_args(argv)
    live_root = args.root.resolve()

    raw = tomllib.loads(args.config.read_text(encoding="utf-8"))
    gateway = raw.get("models", {}).get("gateway", {})
    base_url = str(gateway.get("base_url", "")).strip()
    api_key = str(gateway.get("api_key", "")).strip() or os.environ.get("ATLAS_API_KEY", "")
    default_model = str(raw.get("models", {}).get("default", "")).strip()
    custom_models = raw.get("models", {}).get("custom", [])
    if not base_url or not api_key or not default_model:
        print("MISSING: config lacks gateway base_url / api_key / default model")
        return 2

    if live_root.exists():
        shutil.rmtree(live_root)
    for sub in ("config", "data", "engine", "home", "skills-home", "workspaces",
                "evidence", "mcp-vault", "channel-ws"):
        (live_root / sub).mkdir(parents=True, exist_ok=True)

    custom_blocks = [
        "[[models.custom]]\n"
        f'id = "{model.get("id")}"\n'
        f'name = "{model.get("name")}"\n'
        f'provider = "{model.get("provider")}"\n'
        f'litellm_model = "{model.get("litellm_model") or model.get("id") or ""}"\n'
        f'category = "{model.get("category", "custom")}"\n'
        for model in custom_models
    ]
    vault_dir = (live_root / "mcp-vault").as_posix()
    atlas_toml = (
        "[models]\n"
        f'default = "{default_model}"\n'
        "max_output_tokens = 16384\n\n"
        "[models.gateway]\n"
        f'base_url = "{base_url}"\n'
        f'api_key = "{api_key}"\n\n'
        + "\n".join(custom_blocks)
        + "\n[memory]\n"
        'db_path = "./data/atlas.db"\n\n'
        "[agent]\n"
        'engine = "hermes"\n'
        "verify_before_stop = true\n\n"
        "[tools]\n"
        'auto_start = ["atlas-live-fs"]\n'
        "\n[tools.servers.atlas-live-fs]\n"
        'transport = "stdio"\n'
        'command = "node"\n'
        f'args = ["{FS_SERVER.as_posix()}", "{vault_dir}"]\n'
        "enabled = true\n\n"
        "[scheduler]\n"
        "enabled = false\n\n"
        "[logging]\n"
        'level = "INFO"\n'
        'format = "json"\n'
    )
    (live_root / "config" / "atlas.toml").write_text(atlas_toml, encoding="utf-8")
    # Scenario 11's file lives outside every run workspace: only the MCP tool can read it.
    (live_root / "mcp-vault" / "vault.txt").write_text(
        "Atlas 保密笔记（测试夹具）\n魔数：9137\n仅供 MCP filesystem 工具读取，别处不得出现这个文件。\n",
        encoding="utf-8",
    )
    (live_root / "engine" / "config.yaml").write_text(
        "model:\n"
        "  provider: custom\n"
        f"  base_url: {base_url}\n"
        f"  default: {default_model}\n"
        "  context_length: 65536\n"
        "agent:\n"
        "  api_max_retries: 2\n"
        "auxiliary:\n"
        "  title_generation:\n"
        "    model_upgrade_enabled: false\n"
        "telemetry:\n"
        "  shared_metrics:\n"
        "    enabled: false\n",
        encoding="utf-8",
    )
    (live_root / "engine" / ".env").write_text(f"OPENAI_API_KEY={api_key}\n", encoding="utf-8")
    (live_root / "data" / "user-settings.json").write_text(json.dumps({
        "compression_model": default_model,
        "default_workspace": (live_root / "channel-ws").as_posix(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"live_root={live_root}")
    print(f"gateway_base_url={base_url}")
    print(f"default_model={default_model}")
    print("api_key=<redacted>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
