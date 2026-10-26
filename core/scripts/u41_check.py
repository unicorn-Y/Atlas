"""U41 acceptance scenarios and the complete cumulative regression suite."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
NODE = shutil.which("node.exe") or shutil.which("node") or "node"
PYTHON_FILES = [
    "core/atlas/api/device_router.py",
    "core/atlas/origin_guard.py",
    "core/atlas/tools/x2/registration.py",
    "core/atlas/tools/nodes.py",
    "core/atlas/models/routes.py",
    "core/atlas/pet_store.py",
    "core/atlas/api/pets_router.py",
    "core/atlas/api/application.py",
    "core/atlas/cli.py",
    "core/tests/test_u41_pets.py",
    "core/tests/test_u41_desktop_cli.py",
    "core/tests/test_u41_node_rpc.py",
    "core/tests/test_u41_provider_account_usage.py",
    "core/scripts/u41_check.py",
]


def run(
    label: str,
    args: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    timeout: int = 900,
) -> None:
    print(f"\n=== {label} ===", flush=True)
    result = subprocess.run(
        args, cwd=cwd, env=env, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr)[-6000:]
        raise SystemExit(f"{label} failed with exit code {result.returncode}:\n{detail}")
    output = result.stdout.strip()
    if output:
        print(output[-1000:], flush=True)
    print(f"PASS: {label}", flush=True)


def main() -> None:
    env = os.environ.copy()
    env["ATLAS_ROOT"] = r"C:\engine-reg\_atlasroot"
    env["PYTHONPATH"] = str(ROOT / "core") + os.pathsep + env.get("PYTHONPATH", "")

    run("U41 real scenarios: node RPC, provider account API, pet packages and desktop CLI", [
        sys.executable, "-m", "pytest", "-q",
        "core/tests/test_u41_node_rpc.py",
        "core/tests/test_u41_provider_account_usage.py",
        "core/tests/test_u41_pets.py",
        "core/tests/test_u41_desktop_cli.py",
        "core/tests/test_u40_title_generation.py",
    ], env=env)
    run("Python compileall", [sys.executable, "-m", "compileall", "-q", *PYTHON_FILES], env=env)
    run("pyflakes changed Python", ["uvx", "pyflakes", *PYTHON_FILES], env=env)
    run("pylint changed Python", [
        "uvx", "--from", "pylint", "pylint", "--disable=all",
        "--enable=used-before-assignment,undefined-variable", *PYTHON_FILES,
    ], env=env)

    run("renderer TypeScript", [NODE, "../node_modules/typescript/bin/tsc", "-p", "tsconfig.renderer.json", "--noEmit"], cwd=FRONTEND, env=env)
    run("Electron TypeScript", [NODE, "../node_modules/typescript/bin/tsc", "-p", "tsconfig.electron.json"], cwd=FRONTEND, env=env)
    run("Vite production build", [NODE, "../node_modules/vite/bin/vite.js", "build"], cwd=FRONTEND, env=env)
    run("UI static check", [sys.executable, "core/scripts/ui_static_check.py"], env=env)

    regressions = [
        ("core/scripts/w1_live_smoke.py", []),
        ("core/scripts/w2_live_smoke.py", []),
        ("core/scripts/w10_live_smoke.py", []),
        *[(f"core/scripts/u{number}_check.py", []) for number in range(4, 41)],
        ("core/scripts/u8_check.py", ["--live"]),
    ]
    for script, extra in regressions:
        timeout = 3600 if Path(script).name == "u40_check.py" else 1800 if script == "core/scripts/u8_check.py" and extra else 900
        run(
            f"Regression {Path(script).name} {' '.join(extra)}".strip(),
            [sys.executable, script, *extra], env=env, timeout=timeout,
        )

    print("U41 CHECK PASS", flush=True)


if __name__ == "__main__":
    main()
