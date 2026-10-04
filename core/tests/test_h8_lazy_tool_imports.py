"""H8 O1/O2 regression guard: lazy tool re-exports (taskbook §10 startup).

``import atlas.agent`` must not pull the heavy mcp/tools chain (~1.3s of the
H8 import budget, see tasks/results/ATLAS-H1-H8-lifespan-spec.md §3 O1/O2),
while every historical re-export keeps resolving:

* ``atlas.agent.MCPClient`` / ``ComputerUseRuntime`` / ``LocalExecutionRuntime``
  / ``extract_web`` — PEP 562 module ``__getattr__`` (annotation-only usage
  moved behind ``TYPE_CHECKING``);
* ``atlas.tools.MCPClient`` / ``ToolInfo`` — PEP 562 lazy re-export so light
  submodules (e.g. ``atlas.tools.output_limits``) stay cheap to import.

The subprocess probe is hermetic (no network, no data dir, ~1s); the rest is
in-process.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

CORE_ROOT = Path(__file__).resolve().parents[1]

_PROBE = """
import sys
import atlas.agent, atlas.tools

heavy = [
    m for m in sys.modules
    if m.startswith("mcp")
    or m in {
        "atlas.tools.mcp_client",
        "atlas.tools.computer_use",
        "atlas.tools.local_execution",
        "atlas.tools.web_extract",
    }
]
assert not heavy, f"heavy modules loaded eagerly: {heavy}"

from atlas.agent import (
    ComputerUseRuntime,
    LocalExecutionRuntime,
    MCPClient,
    extract_web,
)
from atlas.tools import MCPClient as ToolsMCPClient, ToolInfo

assert atlas.agent.MCPClient is MCPClient is ToolsMCPClient
assert atlas.tools.ToolInfo is ToolInfo
assert extract_web.__module__ == "atlas.tools.web_extract"
assert atlas.agent.ComputerUseRuntime is ComputerUseRuntime
assert atlas.agent.LocalExecutionRuntime is LocalExecutionRuntime
assert "MCPClient" in dir(atlas.agent) and "extract_web" in dir(atlas.agent)
assert "MCPClient" in dir(atlas.tools) and "ToolInfo" in dir(atlas.tools)
for module in (atlas.agent, atlas.tools):
    try:
        getattr(module, "definitely_not_exported_42")
    except AttributeError:
        pass
    else:
        raise AssertionError("unknown attribute must raise AttributeError")
print("probe-ok")
"""


def test_import_atlas_agent_stays_light_and_lazy_names_resolve() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [*(str(p) for p in sys.path if p), env.get("PYTHONPATH", "")]
    )
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(CORE_ROOT.parent), env=env, capture_output=True,
        text=True, encoding="utf-8", timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    assert "probe-ok" in result.stdout


def test_agent_and_tools_public_surface_unchanged() -> None:
    import atlas.agent
    import atlas.tools

    assert set(atlas.agent.__all__) == {
        "AgentOrchestrator", "AgentRunContext", "RunCallbacks", "RunRequest",
        "SYSTEM_PROMPT", "ToolExecutionState",
    }
    assert set(atlas.tools.__all__) == {"MCPClient", "ToolInfo"}
    # Star-import keeps the historical surface (tools names are not in __all__).
    namespace: dict[str, object] = {}
    exec("from atlas.agent import *", namespace)
    assert "AgentOrchestrator" in namespace
    assert "MCPClient" not in namespace
