"""Probe command and MCP child environment inheritance rules."""
import os
import subprocess
import sys

from atlas.engine_core.tools.child_process_env import (
    child_process_env,
    mcp_child_process_env,
)


def main() -> None:
    names = (
        "OPENAI_API_KEY", "BRAVE_API_KEY", "W2_FIXTURE_API_KEY",
        "W2_FIXTURE_COLOR", "ATLAS_SCRUB_CHILD_ENV",
    )
    old = {name: os.environ.get(name) for name in names}
    try:
        os.environ.update({
            "OPENAI_API_KEY": "model-secret-sentinel",
            "BRAVE_API_KEY": "brave-secret-sentinel",
            "W2_FIXTURE_API_KEY": "fixture-secret-sentinel",
            "W2_FIXTURE_COLOR": "blue",
        })

        os.environ.pop("ATLAS_SCRUB_CHILD_ENV", None)
        command_env = child_process_env()
        assert "OPENAI_API_KEY" not in command_env
        assert "W2_FIXTURE_API_KEY" in command_env  # no suffix-based filtering
        assert command_env["BRAVE_API_KEY"] == "brave-secret-sentinel"
        assert command_env["W2_FIXTURE_COLOR"] == "blue"
        explicit = child_process_env({"OPENAI_API_KEY": "explicit-sentinel"})
        assert explicit["OPENAI_API_KEY"] == "explicit-sentinel"

        mcp_env = mcp_child_process_env()
        assert mcp_env["BRAVE_API_KEY"] == "brave-secret-sentinel"
        assert mcp_env["OPENAI_API_KEY"] == "model-secret-sentinel"
        observed = subprocess.run(
            [sys.executable, "-c", "import os; print(os.environ['BRAVE_API_KEY'])"],
            env=mcp_env, check=True, capture_output=True, text=True,
        )
        assert observed.stdout.strip() == "brave-secret-sentinel"
        configured = mcp_child_process_env({"W2_FIXTURE_COLOR": "configured"})
        assert configured["W2_FIXTURE_COLOR"] == "configured"

        os.environ["ATLAS_SCRUB_CHILD_ENV"] = "0"
        disabled_env = child_process_env()
        assert disabled_env["OPENAI_API_KEY"] == "model-secret-sentinel"
        assert disabled_env["BRAVE_API_KEY"] == "brave-secret-sentinel"
        assert disabled_env["W2_FIXTURE_API_KEY"] == "fixture-secret-sentinel"
    finally:
        for name, value in old.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
    print("W2-6 command scrub, MCP inheritance, and opt-out: PASS")


if __name__ == "__main__":
    main()
