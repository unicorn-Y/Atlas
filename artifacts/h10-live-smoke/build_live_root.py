"""Build the isolated live-smoke data root from the host's real Atlas config.

Reads D:/Atlas/config/atlas.toml (READ-ONLY; the host install is never
written) and materializes a scratch data root under
C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root with the same configured
gateway (base_url + api_key + default model + custom model entries).

The API key is copied in-process only; this script never prints it, and every
artifact derived from a run must pass through redact_evidence.py.
"""

from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

HOST_CONFIG = Path("D:/Atlas/config/atlas.toml")
LIVE_ROOT = Path("C:/Users/25011/AppData/Local/Temp/h1-k-ws/live-root")


def main() -> int:
    raw = tomllib.loads(HOST_CONFIG.read_text(encoding="utf-8"))
    gateway = raw.get("models", {}).get("gateway", {})
    base_url = str(gateway.get("base_url", "")).strip()
    api_key = str(gateway.get("api_key", "")).strip()
    default_model = str(raw.get("models", {}).get("default", "")).strip()
    custom_models = raw.get("models", {}).get("custom", [])
    if not base_url or not api_key or not default_model:
        print("MISSING: host config lacks gateway base_url/api_key/default model")
        return 2

    if LIVE_ROOT.exists():
        shutil.rmtree(LIVE_ROOT)
    for sub in ("config", "data", "engine", "home", "skills-home", "workspaces", "evidence"):
        (LIVE_ROOT / sub).mkdir(parents=True, exist_ok=True)

    custom_blocks: list[str] = []
    for model in custom_models:
        # Host-shaped custom entry, verbatim: the litellm-style prefixed id
        # stays prefixed. The router fix (Lane M, H10.2-DEFECT-1) derives the
        # bare wire id for the Hermes transport, so the scratch root now
        # exercises the exact host configuration instead of a bare-id
        # workaround.
        litellm_model = str(model.get("litellm_model") or model.get("id") or "")
        custom_blocks.append(
            "[[models.custom]]\n"
            f'id = "{model.get("id")}"\n'
            f'name = "{model.get("name")}"\n'
            f'provider = "{model.get("provider")}"\n'
            f'litellm_model = "{litellm_model}"\n'
            f'category = "{model.get("category", "custom")}"\n'
        )

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
        "auto_start = []\n\n"
        "[tools.servers]\n\n"
        "[scheduler]\n"
        "enabled = false\n\n"
        "[logging]\n"
        'level = "INFO"\n'
        'format = "json"\n'
    )
    (LIVE_ROOT / "config" / "atlas.toml").write_text(atlas_toml, encoding="utf-8")

    # Engine home (HERMES_HOME is stamped by the runtime to <data root>/engine).
    context_length = 131072
    engine_config = (
        "model:\n"
        "  provider: custom\n"
        f"  base_url: {base_url}\n"
        f"  default: {default_model}\n"
        f"  context_length: {context_length}\n"
        "agent:\n"
        "  api_max_retries: 2\n"
        # Isolated engine home has no hermes-setup auxiliary providers; keep
        # title generation on the derived fallback instead of a failed LLM call
        # (same pattern as core/tests/fakes/fake_llm_provider.py).
        "auxiliary:\n"
        "  title_generation:\n"
        "    model_upgrade_enabled: false\n"
        "telemetry:\n"
        "  shared_metrics:\n"
        "    enabled: false\n"
    )
    (LIVE_ROOT / "engine" / "config.yaml").write_text(engine_config, encoding="utf-8")
    (LIVE_ROOT / "engine" / ".env").write_text(f"OPENAI_API_KEY={api_key}\n", encoding="utf-8")

    print(f"live_root={LIVE_ROOT}")
    print(f"gateway_base_url={base_url}")
    print(f"default_model={default_model}")
    print(f"custom_models={[m.get('id') for m in custom_models]}")
    print("api_key=<redacted, copied in-process>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
