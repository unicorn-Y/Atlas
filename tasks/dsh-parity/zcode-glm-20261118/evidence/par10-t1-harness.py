"""PAR-10-T1 sandbox verification: patched in-flight install chain + fake npm/pnpm.

Run with an isolated interpreter, for example:

    python -I par10-t1-harness.py \
        --candidate-core D:/Atlas/.worktrees/zcode-par10-registry-runtime/core \
        --sandbox D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/sandbox \
        --tmp D:/Atlas/.worktrees/zcode-par10-registry-runtime/.tmp/par10-t1/integration

Nothing under the main workspace is modified. The npm/pnpm entries are local
Node scripts that copy a prepared tarball and emit deterministic failures; no
real registry, account, or credential is contacted.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import io
import json
import os
import sys
import tarfile
import types
from pathlib import Path

OFFICIAL = "https://registry.npmjs.org/"
MIRROR = "https://registry.npmmirror.com/"
PRIVATE = "https://npm.private.example.invalid/repository/"
PRIVATE_WITH_CREDENTIALS = "https://build:par10-secret@npm.private.example.invalid/repository/"
SPEC_HOST = "https://git.example.invalid/plugins/demo.tgz"


def _load_runtime(candidate_core: Path, sandbox: Path):
    sys.path.insert(0, str(candidate_core))
    import atlas.plugins as plugins_pkg  # noqa: F401 - package seam for the overlay

    overlay = str(sandbox / "core" / "atlas" / "plugins")
    if overlay not in plugins_pkg.__path__:
        plugins_pkg.__path__.append(overlay)
    common = importlib.util.spec_from_file_location(
        "atlas.plugins.compatibility", sandbox / "core" / "atlas" / "plugins" / "compatibility.py",
    )
    module_common = importlib.util.module_from_spec(common)
    sys.modules["atlas.plugins.compatibility"] = module_common
    common.loader.exec_module(module_common)

    spec = importlib.util.spec_from_file_location(
        "par10_runtime_patched", sandbox / "core" / "atlas" / "plugins" / "runtime.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    router_spec = importlib.util.spec_from_file_location(
        "atlas.api.plugins_router", sandbox / "core" / "atlas" / "api" / "plugins_router.py",
    )
    router = importlib.util.module_from_spec(router_spec)
    sys.modules["atlas.api.plugins_router"] = router
    router_spec.loader.exec_module(router)
    return module.PluginRuntime, router


def _make_package_archive(path: Path) -> None:
    files = {
        "package/package.json": json.dumps({
            "name": "fixture-plugin",
            "version": "1.0.0",
            "dependencies": {"fixture-dependency": "1.0.0"},
        }, ensure_ascii=False),
        "package/plugin.json": json.dumps({
            "name": "fixture-plugin", "version": "1.0.0",
        }, ensure_ascii=False),
        "package/README.md": "fixture\n",
    }
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))


def _write_tool(path: Path, tool: str, archive: Path, log: Path, rules: dict) -> None:
    config = {"tool": tool, "archive": str(archive), "log": str(log), "rules": rules}
    source = f"""
const fs = require('fs');
const path = require('path');
const cfg = {json.dumps(config)};
const args = process.argv.slice(2);
const flag = (name) => {{
  const index = args.indexOf(name);
  return index >= 0 ? args[index + 1] : '';
}};
const registry = args.filter((value) => value.startsWith('--registry='))
  .map((value) => value.slice('--registry='.length))[0] || '';
const cwd = process.cwd();
fs.appendFileSync(cfg.log, JSON.stringify({{tool: cfg.tool, registry, cwd}}) + '\\n');
const rule = cfg.rules[registry] || cfg.rules[registry.replace(/\\/$/, '')] || cfg.rules['*'];
const extra = rule && rule.echoDestination ? `workspace: ${{flag('--pack-destination') || cwd}}\\n` : '';
if (rule && rule.ok) {{
  if (cfg.tool === 'npm') {{
    fs.copyFileSync(cfg.archive, path.join(flag('--pack-destination') || process.cwd(),
      'fixture-plugin-1.0.0.tgz'));
  }}
  process.stdout.write((rule.output || 'ok\\n') + extra);
  process.exit(0);
}}
process.stdout.write((rule && rule.output ? rule.output : '') + extra);
process.exit((rule && rule.code) || 1);
"""
    path.write_text(source, encoding="utf-8")


def _calls(log: Path) -> list[dict]:
    if not log.is_file():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_scenario(
    runtime_cls, tmp: Path, name: str, *, source: str, source_type: str,
    registry: str | None, fallbacks: list[str] | None, npm_rules: dict, pnpm_rules: dict,
) -> dict:
    root = tmp / name
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "fixture-plugin-1.0.0.tgz"
    _make_package_archive(archive)
    log = root / "calls.jsonl"
    npm_entry = root / "fake-npm.cjs"
    pnpm_entry = root / "fake-pnpm.cjs"
    _write_tool(npm_entry, "npm", archive, log, npm_rules)
    _write_tool(pnpm_entry, "pnpm", archive, log, pnpm_rules)
    os.environ["ATLAS_NPM_ENTRY"] = str(npm_entry)
    os.environ["ATLAS_PNPM_ENTRY"] = str(pnpm_entry)
    runtime = runtime_cls([root / "installed"], root / "state.json")

    async def scenario():
        started = await runtime.start_install_operation(
            source, source_type=source_type, registry=registry,
            fallback_registries=fallbacks,
        )
        final = await runtime.wait_install_operation(started["requestId"], wait_seconds=60)
        await runtime.close_install_operations()
        return started, final

    try:
        started, final = asyncio.run(scenario())
    finally:
        runtime._install_tasks.clear()
    return {
        "name": name,
        "started": started,
        "final": final,
        "calls": _calls(log),
        "installed": (root / "installed" / "fixture-plugin" / "plugin.json").is_file(),
    }


def _registries(result: dict, key: str) -> list:
    return [item.get("registry") for item in result.get("final", {}).get(key, [])]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-core", required=True)
    parser.add_argument("--sandbox", required=True)
    parser.add_argument("--tmp", required=True)
    args = parser.parse_args()
    candidate_core = Path(args.candidate_core).resolve()
    sandbox = Path(args.sandbox).resolve()
    tmp = Path(args.tmp).resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    runtime_cls, router_mod = _load_runtime(candidate_core, sandbox)

    npm_ok = {"*": {"ok": True, "output": "added 1 package\n"}}
    pnpm_ok = {"*": {"ok": True, "output": "Packages: +1\nDone\n"}}
    npm_network_fail = {
        OFFICIAL: {
            "ok": False, "code": 1,
            "output": "npm ERR! code ENOTFOUND\nnpm ERR! network request to https://registry.npmjs.org/ failed\n",
        },
        "*": {"ok": True, "output": "added 1 package\n"},
    }
    pnpm_network_fail = {
        OFFICIAL: {
            "ok": False, "code": 1,
            "output": "ERR_PNPM_META_FETCH_FAIL GET https://registry.npmjs.org/fixture-dependency: network error\n",
        },
        "*": {"ok": True, "output": "Packages: +1\nDone\n"},
    }
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, bool(condition), detail))

    # A. normal install through the public registry.
    normal = _run_scenario(
        runtime_cls, tmp, "a-normal", source="npm:fixture-plugin", source_type="npm",
        registry=OFFICIAL, fallbacks=[MIRROR], npm_rules=npm_ok, pnpm_rules=pnpm_ok,
    )
    check("A completed", normal["final"].get("status") == "completed")
    check("A installed", normal["installed"])
    check("A one npm attempt", [c["tool"] for c in normal["calls"]].count("npm") == 1)
    check("A plan ordered public+fallback",
          normal["started"].get("registryPlan", {}).get("registries") == [OFFICIAL, MIRROR])
    check("A no failure attribution", "failureAttribution" not in normal["final"])

    # B. public registry fails, configured mirror answers both pack and install.
    fallback = _run_scenario(
        runtime_cls, tmp, "b-fallback", source="npm:fixture-plugin", source_type="npm",
        registry=OFFICIAL, fallbacks=[MIRROR], npm_rules=npm_network_fail, pnpm_rules=pnpm_network_fail,
    )
    calls_b = [(c["tool"], c["registry"]) for c in fallback["calls"]]
    check("B completed", fallback["final"].get("status") == "completed")
    check("B npm fallback order", [c for c in calls_b if c[0] == "npm"] == [("npm", OFFICIAL), ("npm", MIRROR)])
    check("B pnpm fallback order", [c for c in calls_b if c[0] == "pnpm"] == [("pnpm", OFFICIAL), ("pnpm", MIRROR)])
    check("B pack attempts recorded",
          _registries(fallback, "registryAttempts") == [OFFICIAL, MIRROR])
    check("B dependency attempts recorded",
          _registries(fallback, "dependencyAttempts") == [OFFICIAL, MIRROR])

    # C. explicit private registry fails: no public fallback.
    private = _run_scenario(
        runtime_cls, tmp, "c-private", source="npm:fixture-plugin", source_type="npm",
        registry=PRIVATE, fallbacks=[MIRROR],
        npm_rules={PRIVATE: {"ok": False, "code": 1, "output": "npm ERR! code E404\nnpm ERR! 404 Not Found\n"}, "*": {"ok": True}},
        pnpm_rules=pnpm_ok,
    )
    check("C failed", private["final"].get("status") == "failed")
    check("C only private asked", [c["registry"] for c in private["calls"]] == [PRIVATE])
    check("C plan single source",
          private["started"].get("registryPlan", {}).get("registries") == [PRIVATE])
    check("C refusal recorded",
          private["started"].get("registryPlan", {}).get("registryRefusal")
          == "requested-registry-not-configured")
    check("C attribution registry", private["final"].get("failureAttribution") == "registry")

    # D. spec carries its own host: a failure there is not retried on a registry.
    spec_host = _run_scenario(
        runtime_cls, tmp, "d-spec-host", source=SPEC_HOST, source_type="npm",
        registry=OFFICIAL, fallbacks=[MIRROR],
        npm_rules={OFFICIAL: {
            "ok": False, "code": 1,
            "output": "fatal: unable to access 'https://git.example.invalid/plugins/demo.tgz': "
                      "Could not resolve host: git.example.invalid\n",
        }, "*": {"ok": True}},
        pnpm_rules=pnpm_ok,
    )
    check("D failed", spec_host["final"].get("status") == "failed")
    check("D only first registry asked", [c["registry"] for c in spec_host["calls"]] == [OFFICIAL])
    check("D plan marks tarball host",
          spec_host["started"].get("registryPlan", {}).get("specKind") == "tarball"
          and spec_host["started"].get("registryPlan", {}).get("specHost") == "git.example.invalid")
    check("D attribution spec-host", spec_host["final"].get("failureAttribution") == "spec-host")
    check("D fallback refused", spec_host["final"].get("registryOutcome", {}).get("fallbackRefused") is True)

    # E. credentials are issued to npm but never stored in install state.
    leaked = _run_scenario(
        runtime_cls, tmp, "e-redaction", source="npm:fixture-plugin", source_type="npm",
        registry=PRIVATE_WITH_CREDENTIALS, fallbacks=[],
        npm_rules={PRIVATE_WITH_CREDENTIALS: {
            "ok": False, "code": 1,
            "output": f"npm ERR! request to {PRIVATE_WITH_CREDENTIALS} failed\n"
                      "npm ERR! //npm.private.example.invalid/:_authToken=par10-token\n"
                      "npm ERR! cache C:\\Users\\alice\\private\\npm-cache\n",
            "echoDestination": True,
        }, "*": {"ok": True}},
        pnpm_rules=pnpm_ok,
    )
    serialized = json.dumps(leaked["final"], ensure_ascii=False)
    workspace = str(leaked["calls"][0].get("cwd", "")) if leaked["calls"] else ""
    check("E failed", leaked["final"].get("status") == "failed")
    check("E raw credential issued to npm",
          [c["registry"] for c in leaked["calls"]] == [PRIVATE_WITH_CREDENTIALS])
    for secret in ("par10-secret", "par10-token", "alice"):
        check(f"E state hides {secret!r}", secret not in serialized)
    check("E full workspace path redacted", bool(workspace) and workspace not in serialized)
    check("E plan URL has no credentials",
          leaked["started"].get("registryPlan", {}).get("registries") == [PRIVATE])
    check("E redaction marker present",
          "<redacted>" in json.dumps(leaked["final"].get("registryAttempts", [])))

    # F. unknown pnpm-owned registry is asked alone despite configured fallbacks.
    own = _run_scenario(
        runtime_cls, tmp, "f-pnpm-own", source="npm:fixture-plugin", source_type="npm",
        registry=None, fallbacks=[MIRROR],
        npm_rules={"*": {"ok": False, "code": 1, "output": "npm ERR! code ENOTFOUND\n"}},
        pnpm_rules=pnpm_ok,
    )
    check("F failed", own["final"].get("status") == "failed")
    check("F only one attempt", len(own["calls"]) == 1)
    check("F plan pnpm-own-unknown",
          own["started"].get("registryPlan", {}).get("decision") == "pnpm-own-unknown")
    check("F no mirror", all(c["registry"] != MIRROR for c in own["calls"]))

    # G. the HTTP install endpoint forwards fallbackRegistries into the runtime.
    router_root = tmp / "g-router"
    router_root.mkdir(parents=True, exist_ok=True)
    local_source = router_root / "local-plugin"
    local_source.mkdir()
    (local_source / "plugin.json").write_text(
        json.dumps({"name": "local-plugin", "version": "1.0.0"}), encoding="utf-8",
    )
    router_runtime = runtime_cls([router_root / "installed"], router_root / "state.json")

    async def router_refresh():
        return {"loaded": []}

    router_mod._server = lambda: types.SimpleNamespace(_reload_extensions=router_refresh)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from atlas.api.app_services import AppServices

    app = FastAPI()
    app.state.services = AppServices(plugin_runtime=router_runtime)
    app.include_router(router_mod.router)
    with TestClient(app) as client:
        response = client.post("/api/plugins/install", json={
            "source": str(local_source), "registry": OFFICIAL,
            "fallbackRegistries": [MIRROR], "requestId": "router-fallback-1",
        })
        routed = response.json()
        routed_final = client.get("/api/plugins/install/router-fallback-1?wait_ms=5000").json()
        invalid = client.post("/api/plugins/install", json={
            "source": str(local_source), "fallbackRegistries": "not-a-list",
        }).status_code
    asyncio.run(router_runtime.close_install_operations())
    check("G endpoint accepted request",
          response.status_code == 200
          and routed.get("registryPlan", {}).get("registries") == [OFFICIAL, MIRROR])
    check("G routed install completed", routed_final.get("status") == "completed")
    check("G invalid fallback rejected", invalid == 422)

    print(json.dumps({
        "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
        "scenarios": {
            "a-normal": {"status": normal["final"].get("status"), "plan": normal["started"].get("registryPlan")},
            "b-fallback": {
                "status": fallback["final"].get("status"),
                "error": fallback["final"].get("error"),
                "failureType": fallback["final"].get("failureType"),
                "failureAttribution": fallback["final"].get("failureAttribution"),
                "calls": calls_b,
                "pack": _registries(fallback, "registryAttempts"),
                "dependencies": _registries(fallback, "dependencyAttempts"),
            },
            "c-private": {"status": private["final"].get("status"), "attribution": private["final"].get("failureAttribution")},
            "d-spec-host": {"status": spec_host["final"].get("status"), "attribution": spec_host["final"].get("failureAttribution")},
            "e-redaction": {"failureKind": leaked["final"].get("failureKind"), "attempts": len(leaked["final"].get("registryAttempts", []))},
            "f-pnpm-own": {"status": own["final"].get("status"), "decision": own["started"].get("registryPlan", {}).get("decision")},
            "g-router": {"status": routed_final.get("status"), "plan": routed.get("registryPlan")},
        },
    }, ensure_ascii=False, indent=2))
    failed = [name for name, ok, _detail in checks if not ok]
    print(f"PAR10_T1_HARNESS {'PASS' if not failed else 'FAIL'} ({len(checks) - len(failed)}/{len(checks)})")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())