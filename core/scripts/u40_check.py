from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
NODE = shutil.which("node") or "node"
PYTHON_FILES = [
    "core/atlas/api/integrations_router.py",
    "core/atlas/api/linear_integration_router.py",
    "core/atlas/agent/tool_catalog.py",
    "core/atlas/agent/tool_node.py",
    "core/atlas/api/conversations_router.py",
]


def run(label: str, args: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(args, cwd=cwd, env=env, check=False)
    if result.returncode:
        raise SystemExit(f"{label} failed with exit code {result.returncode}")


def main() -> None:
    env = os.environ.copy()
    env["ATLAS_ROOT"] = r"C:\engine-reg\_atlasroot"
    env["ATLAS_U7_SKIP_SCREENSHOTS"] = "1"
    env["PYTHONPATH"] = str(ROOT / "core") + os.pathsep + env.get("PYTHONPATH", "")

    run("U40 real scenarios: connectors, metadata, title, workspace file history", [
        sys.executable, "-m", "pytest", "-q",
        "core/tests/test_u40_connectors.py",
        "core/tests/test_u40_conversation_metadata.py",
        "core/tests/test_u40_title_generation.py",
        "core/tests/test_backend_parity_wave4.py::test_workspace_history_orders_versions_and_snapshots_before_restore",
    ], env=env)
    run("Python compileall", [sys.executable, "-m", "compileall", "-q", *PYTHON_FILES], env=env)
    run("pyflakes changed Python", ["uvx", "pyflakes", *PYTHON_FILES], env=env)
    run("pylint changed Python", ["uvx", "--from", "pylint", "pylint", "--disable=all", "--enable=used-before-assignment,undefined-variable", *PYTHON_FILES], env=env)

    run("renderer TypeScript", [NODE, "../node_modules/typescript/bin/tsc", "-p", "tsconfig.renderer.json", "--noEmit"], cwd=FRONTEND, env=env)
    run("Electron TypeScript", [NODE, "../node_modules/typescript/bin/tsc", "-p", "tsconfig.electron.json"], cwd=FRONTEND, env=env)
    run("Vite production build", [NODE, "../node_modules/vite/bin/vite.js", "build"], cwd=FRONTEND, env=env)
    run("UI static check", [sys.executable, "core/scripts/ui_static_check.py"], env=env)

    regressions = [
        ("core/scripts/w1_live_smoke.py", []), ("core/scripts/w2_live_smoke.py", []),
        ("core/scripts/w10_live_smoke.py", []),
        *[(f"core/scripts/u{number}_check.py", []) for number in range(4, 40)],
        ("core/scripts/u8_check.py", ["--live"]),
    ]
    for script, extra in regressions:
        run(f"Regression {Path(script).name} {' '.join(extra)}".strip(), [sys.executable, script, *extra], env=env)

    print("U40 CHECK PASS", flush=True)


if __name__ == "__main__":
    main()
