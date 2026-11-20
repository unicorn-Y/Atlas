from __future__ import annotations

import json
import hashlib
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
try:
    import dsh_capability_audit  # noqa: E402
    from dsh_capability_audit import (  # noqa: E402
        build_source_index, check_source_index, scan_to_ledger,
    )
except ImportError:
    dsh_capability_audit = None
    build_source_index = check_source_index = scan_to_ledger = None
try:
    import dsh_shell_parse  # noqa: E402
except ImportError:
    dsh_shell_parse = None
try:
    from dsh_validation_runner import ProcessIdentity, run_command, signal_if_same_process  # noqa: E402
except ImportError:
    ProcessIdentity = run_command = signal_if_same_process = None


pytestmark = pytest.mark.unit


def _source(root: Path) -> None:
    package = root / "packages" / "fixture"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps({
        "name": "@fixture/feature",
        "exports": {".": "./src/index.ts"},
    }), encoding="utf-8")
    source = package / "src" / "index.ts"
    source.parent.mkdir()
    source.write_text(
        "export function run(): string {\n"
        "  if (process.platform === 'win32') return 'windows';\n"
        "  return 'portable';\n"
        "}\n",
        encoding="utf-8",
    )
    config = root / "config" / "settings.json"
    config.parent.mkdir()
    config.write_text(json.dumps({"retry": {"type": "integer", "default": 3}}, indent=2),
                      encoding="utf-8")


def _require_audit_functions():
    assert callable(build_source_index) and callable(check_source_index) and callable(scan_to_ledger), (
        "the DSH source audit scanner is not implemented yet"
    )


def _typescript_compiler() -> Path | None:
    configured = Path("D:/ENGINE-V3-UPSTREAM-20261011/deepseek-harness/node_modules/typescript/lib/typescript.js")
    return configured if configured.is_file() else None


def test_typescript_extractor_child_has_an_explicit_heap_ceiling(tmp_path, monkeypatch):
    compiler = tmp_path / "typescript.js"
    compiler.write_text("// fixture compiler path", encoding="utf-8")
    captured = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps([{"path": "fixture.ts", "contracts": [], "parse_diagnostics": []}]),
            stderr="",
        )

    monkeypatch.setattr(dsh_capability_audit.subprocess, "run", fake_run)

    result = dsh_capability_audit._typescript_function_contracts(
        tmp_path, {"fixture.ts": b"export function run() { return 1 }\n"}, compiler,
    )

    assert captured["command"][1] == "--max-old-space-size=8192"
    assert result["fixture.ts"]["contracts"] == []


def test_semantic_decisions_can_map_package_entry_points(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    manifest_path = tmp_path / "packages" / "fixture" / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bin"] = {"fixture": "lib/bin.js"}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    compiler = _typescript_compiler()
    initial = build_source_index(tmp_path, typescript_module=compiler)
    entry = next(item for item in initial["entry_points"] if item["kind"] == "package_bin")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "atomic-capabilities.jsonl").write_text(
        json.dumps({"atomic_id": "TEST-PACKAGE-BIN"}) + "\n", encoding="utf-8",
    )
    (ledger / "interaction-edges.jsonl").write_text(
        json.dumps({"edge_id": "EDGE-TEST-PACKAGE-BIN"}) + "\n", encoding="utf-8",
    )
    decision = {
        "schema_version": 1,
        "source_head": initial["source"]["head"],
        "entry_id": entry["entry_id"],
        "digest": entry["digest"],
        "resolution": "MAPPED",
        "atomic_ids": ["TEST-PACKAGE-BIN"],
        "interaction_ids": ["EDGE-TEST-PACKAGE-BIN"],
        "evidence": ["Reviewed the package bin field and its launcher consumer."],
    }
    (ledger / "semantic-decisions.jsonl").write_text(
        json.dumps(decision) + "\n", encoding="utf-8",
    )

    indexed = scan_to_ledger(tmp_path, ledger, typescript_module=compiler)

    mapped = next(item for item in indexed["entry_points"] if item["entry_id"] == entry["entry_id"])
    assert mapped["resolution"] == "MAPPED"
    assert mapped["atomic_ids"] == ["TEST-PACKAGE-BIN"]
    assert mapped["interaction_ids"] == ["EDGE-TEST-PACKAGE-BIN"]


def test_entry_point_decisions_reject_unknown_stale_and_dangling_targets(tmp_path):
    _require_audit_functions()
    source = tmp_path / "source"
    _source(source)
    manifest_path = source / "packages" / "fixture" / "package.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["bin"] = {"fixture": "lib/bin.js"}
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    index = build_source_index(source)
    entry = next(item for item in index["entry_points"] if item["kind"] == "package_bin")
    ledger = tmp_path / "ledger"
    ledger.mkdir()
    (ledger / "atomic-capabilities.jsonl").write_text(
        json.dumps({"atomic_id": "TEST-PACKAGE-BIN"}) + "\n", encoding="utf-8",
    )
    (ledger / "interaction-edges.jsonl").write_text(
        json.dumps({"edge_id": "EDGE-TEST-PACKAGE-BIN"}) + "\n", encoding="utf-8",
    )
    base_decision = {
        "schema_version": 1,
        "source_head": index["source"]["head"],
        "entry_id": entry["entry_id"],
        "digest": entry["digest"],
        "resolution": "MAPPED",
        "atomic_ids": ["TEST-PACKAGE-BIN"],
        "interaction_ids": ["EDGE-TEST-PACKAGE-BIN"],
        "evidence": ["Reviewed the package entry target and CLI startup consumer."],
    }

    cases = (
        ({**base_decision, "entry_id": "DSH-UNKNOWN-ENTRY"}, "unknown entry"),
        ({**base_decision, "digest": "0" * 64}, "stale semantic decision"),
        ({**base_decision, "atomic_ids": ["MISSING-ATOM"]}, "missing atomic row"),
        ({**base_decision, "interaction_ids": ["MISSING-EDGE"]}, "missing interaction row"),
    )
    for decision, expected_error in cases:
        (ledger / "semantic-decisions.jsonl").write_text(
            json.dumps(decision) + "\n", encoding="utf-8",
        )
        with pytest.raises(ValueError, match=expected_error):
            scan_to_ledger(source, ledger)


def test_source_index_records_files_components_exports_and_semantic_units(tmp_path):
    _require_audit_functions()
    _source(tmp_path)

    index = build_source_index(tmp_path)

    paths = {item["path"] for item in index["files"]}
    assert paths == {
        "packages/fixture/package.json",
        "packages/fixture/src/index.ts",
        "config/settings.json",
    }
    assert index["components"][0]["component_id"] == "@fixture/feature"
    assert index["components"][0]["exports"] == {".": "./src/index.ts"}
    units = index["semantic_coverage"]
    assert {item["kind"] for item in units} >= {
        "export", "platform_branch", "configuration_default",
    }
    assert all(item["unit_id"] and item["digest"] for item in units)
    assert all(item["resolution"] == "UNRESOLVED" for item in units)
    json_default = next(
        item for item in units
        if item["kind"] == "configuration_field"
        and item.get("contract", {}).get("field_path") == "retry.default"
    )
    assert json_default["line"] == 4
    assert json_default["contract"]["value_digest"]


def test_css_style_rules_are_semantic_units_with_nested_scope_and_declarations(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    stylesheet = tmp_path / "assets" / "picker.css"
    stylesheet.parent.mkdir(parents=True)
    stylesheet.write_text(
        "/* ignored .fake { color: red } */\n"
        "@import url('./base.css');\n"
        ".picker, .picker[data-open=\"true\"] {\n"
        "  display: grid;\n"
        "  content: \"semi; brace { stays in a string\";\n"
        "  &:focus-visible { outline: 2px solid currentColor; }\n"
        "}\n"
        "@media (max-width: 30rem) {\n"
        "  .picker { grid-template-columns: 1fr; }\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)

    file_row = next(item for item in index["files"] if item["path"].endswith("picker.css"))
    assert file_row["classification"] == "source"
    units = [item for item in index["semantic_coverage"] if item["path"].endswith("picker.css")]
    rules = [item for item in units if item["kind"] == "css_rule"]
    assert len(rules) == 4
    assert all(item["digest"] and item["line"] > 0 for item in rules)
    picker = next(item for item in rules if item["contract"].get("prelude") == '.picker, .picker[data-open="true"]')
    assert {item["property"] for item in picker["contract"]["declarations"]} == {"display", "content"}
    assert all(item["value_sha256"] for item in picker["contract"]["declarations"])
    nested = next(item for item in rules if item["contract"].get("prelude") == "&:focus-visible")
    assert nested["contract"]["parents"] == ['.picker, .picker[data-open="true"]']
    media = next(item for item in rules if item["contract"].get("prelude") == "@media (max-width: 30rem)")
    assert media["contract"]["rule_type"] == "at_rule"
    mobile_picker = next(item for item in rules if item["contract"].get("prelude") == ".picker"
                         and item["contract"]["parents"] == ["@media (max-width: 30rem)"])
    assert mobile_picker["contract"]["declarations"][0]["property"] == "grid-template-columns"
    directive = next(item for item in units if item["kind"] == "css_directive")
    assert directive["contract"]["prelude"] == "@import url('./base.css')"
    assert all(item["resolution"] == "UNRESOLVED" for item in units)
    assert len({item["unit_id"] for item in units}) == len(units)
    assert units == [item for item in build_source_index(tmp_path)["semantic_coverage"]
                     if item["path"].endswith("picker.css")]


def test_css_unclosed_rule_is_retained_as_unresolved_obligation(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    stylesheet = tmp_path / "styles.css"
    stylesheet.write_text(".panel { display: grid;\n", encoding="utf-8")

    index = build_source_index(tmp_path)

    unresolved = [item for item in index["semantic_coverage"]
                  if item["path"] == "styles.css" and item["kind"] == "css_parse_unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["contract"]["prelude"] == ".panel"
    assert unresolved[0]["contract"]["source_span"]["start_line"] == 1


def test_source_index_assigns_deterministic_component_and_repository_scopes(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({"name": "@fixture/root"}), encoding="utf-8")
    (tmp_path / "README.md").write_text("repository-owned notes\n", encoding="utf-8")

    index = build_source_index(tmp_path)
    repeated = build_source_index(tmp_path)

    scopes = {item["scope_id"]: item for item in index["scopes"]}
    files = {item["path"]: item for item in index["files"]}
    units = index["semantic_coverage"]
    assert files["packages/fixture/src/index.ts"]["scope_id"] == "component:@fixture/feature"
    assert files["package.json"]["scope_id"] == "component:@fixture/root"
    assert files["package.json"]["component_id"] == "@fixture/root"
    assert files["README.md"]["scope_id"] == "repository:root"
    assert files["config/settings.json"]["scope_id"] == "repository:config"
    assert all(item.get("scope_id") for item in files.values())
    assert all(item.get("scope_id") for item in units)
    assert sum(item["file_count"] for item in scopes.values()) == len(files)
    assert sum(item["semantic_unit_count"] for item in scopes.values()) == len(units)
    assert [(item["scope_id"], item["file_count"], item["semantic_unit_count"])
            for item in index["scopes"]] == [
        (item["scope_id"], item["file_count"], item["semantic_unit_count"])
        for item in repeated["scopes"]
    ]
    assert all(item["resolution"] == "UNRESOLVED" for item in units)


def test_check_rejects_internal_semantic_change_without_package_change(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    baseline = build_source_index(tmp_path)
    source = tmp_path / "packages" / "fixture" / "src" / "index.ts"
    source.write_text(source.read_text(encoding="utf-8") +
                      "\nfunction addedInsideComponent() {\n  if (process.platform === 'darwin') return;\n}\n",
                      encoding="utf-8")
    config = tmp_path / "config" / "settings.json"
    config.write_text(config.read_text(encoding="utf-8").replace(": 3", ": 4"), encoding="utf-8")

    findings = check_source_index(tmp_path, baseline)

    assert any(item["code"] == "SOURCE_DIGEST_CHANGED" for item in findings)
    assert any(item["code"] == "SEMANTIC_UNIT_ADDED" for item in findings)
    assert any(item.get("path") == "config/settings.json" for item in findings)


def test_semantic_coverage_indexes_exception_and_cancellation_cleanup_obligations(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    source = tmp_path / "packages" / "fixture" / "src" / "lifecycle.py"
    source.write_text(
        "async def run_lifecycle():\n"
        "    try:\n"
        "        await run()\n"
        "    except asyncio.CancelledError:\n"
        "        await release_owner_resources()\n"
        "        raise\n"
        "    except TimeoutError:\n"
        "        await release_owner_resources()\n"
        "        raise\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)

    branches = [
        item for item in index["semantic_coverage"]
        if item["path"] == "packages/fixture/src/lifecycle.py"
        and item["kind"] == "exception_branch"
    ]
    assert {item["symbol"] for item in branches} == {
        "asyncio.CancelledError", "TimeoutError",
    }
    assert all(item["resolution"] == "UNRESOLVED" for item in branches)
    assert all(item["unit_id"] and item["digest"] and item["line"] > 0 for item in branches)


def test_python_method_contract_captures_defaults_exception_platform_and_state(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    source = tmp_path / "packages" / "fixture" / "src" / "lifecycle.py"
    source.write_text(
        "import sys\n"
        "class Engine:\n"
        "    async def start(self, mode='safe', attempts: int = 2):\n"
        "        try:\n"
        "            if sys.platform == 'win32':\n"
        "                self.state = 'running'\n"
        "        except OSError:\n"
        "            self.state = 'failed'\n"
        "            raise\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)

    method = next(
        item for item in index["semantic_coverage"]
        if item["path"] == "packages/fixture/src/lifecycle.py"
        and item.get("contract", {}).get("qualname") == "Engine.start"
    )
    contract = method["contract"]
    assert contract["kind"] == "python_method"
    assert contract["async"] is True
    assert contract["source_span"] == {"start_line": 3, "end_line": 9}
    assert [(item["name"], item["default_digest"]) for item in contract["parameters"]] == [
        ("self", None),
        ("mode", hashlib.sha256(b"'safe'").hexdigest()),
        ("attempts", hashlib.sha256(b"2").hexdigest()),
    ]
    assert contract["obligations"]["exceptions"] == [{"type": "OSError", "line": 7}]
    platform_branches = contract["obligations"]["platform_branches"]
    assert len(platform_branches) == 1 and platform_branches[0]["line"] == 5
    assert platform_branches[0]["expression_digest"]
    state_transitions = contract["obligations"]["state_transitions"]
    assert [(item["target"], item["line"]) for item in state_transitions] == [
        ("self.state", 6), ("self.state", 8),
    ]
    assert all(item["value_digest"] for item in state_transitions)
    assert method["resolution"] == "UNRESOLVED"


def test_typescript_and_javascript_ast_contracts_capture_methods_callers_and_obligations(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    typescript = tmp_path / "packages" / "fixture" / "src" / "engine.ts"
    typescript.write_text(
        "class Engine {\n"
        "  async run(mode = 'safe') {\n"
        "    try {\n"
        "      if (process.platform === 'win32') this.status = 'running';\n"
        "      return await this.commit(mode);\n"
        "    } catch (error) {\n"
        "      this.phase = 'failed';\n"
        "      throw new Error('failed');\n"
        "    }\n"
        "  }\n"
        "  async commit(mode: string) { return mode; }\n"
        "}\n"
        "const invoke = (tries = 3) => new Engine().run(String(tries));\n",
        encoding="utf-8",
    )
    javascript = tmp_path / "packages" / "fixture" / "src" / "consumer.js"
    javascript.write_text(
        "async function consume(value = 'default') {\n"
        "  if (process.platform === 'linux') return value;\n"
        "  throw new Error('unsupported');\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path, typescript_module=compiler)
    repeated = build_source_index(tmp_path, typescript_module=compiler)
    assert index["semantic_coverage"] == repeated["semantic_coverage"]
    contracts = {
        item["contract"]["qualname"]: item
        for item in index["semantic_coverage"]
        if item["kind"] == "typescript_function_contract"
    }
    run = contracts["Engine.run"]["contract"]
    assert run["kind"] == "typescript_method"
    assert run["async"] is True
    assert run["source_span"] == {"start_line": 2, "end_line": 10}
    assert run["parameters"] == [{
        "name": "mode", "optional": True,
        "default_digest": hashlib.sha256(b"'safe'").hexdigest(),
    }]
    assert any(item["kind"] == "catch" for item in run["obligations"]["exceptions"])
    assert any(item["kind"] == "throw" for item in run["obligations"]["exceptions"])
    assert run["obligations"]["platform_branches"]
    assert [item["target"] for item in run["obligations"]["state_transitions"]] == [
        "this.status", "this.phase",
    ]
    assert run["caller_edges"] == [{
        "callee": "Engine.commit", "line": 5,
        "resolution": "same_file_unique_name",
    }]
    invoke = contracts["invoke"]["contract"]
    assert invoke["parameters"][0]["default_digest"] == hashlib.sha256(b"3").hexdigest()
    assert invoke["caller_edges"] == [{
        "callee": "Engine.run", "line": 13,
        "resolution": "same_file_unique_name",
    }]
    js_consume = next(
        item["contract"] for item in index["semantic_coverage"]
        if item["kind"] == "typescript_function_contract"
        and item["path"].endswith("consumer.js")
    )
    assert js_consume["kind"] == "javascript_function"
    assert js_consume["obligations"]["platform_branches"]
    assert "safe" not in json.dumps(run)
    assert '"3"' not in json.dumps(invoke)


def test_typescript_cross_file_callers_resolve_barrel_aliases_and_mark_external_imports(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    source_dir = tmp_path / "packages" / "fixture" / "src"
    library = source_dir / "library.ts"
    library.write_text(
        "export function execute(): string { return 'ok'; }\n"
        "export class Engine { run(): string { return execute(); } }\n",
        encoding="utf-8",
    )
    barrel = source_dir / "barrel.ts"
    barrel.write_text(
        "export { execute as launch, Engine } from './library';\n",
        encoding="utf-8",
    )
    consumer = source_dir / "consumer.ts"
    consumer.write_text(
        "import { launch, Engine } from './barrel';\n"
        "import { readFile } from 'node:fs/promises';\n"
        "export async function invoke() {\n"
        "  launch();\n"
        "  new Engine().run();\n"
        "  await readFile('fixture');\n"
        "  await import('./library');\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path, typescript_module=compiler)
    repeated = build_source_index(tmp_path, typescript_module=compiler)
    contracts = {
        (item["path"], item["contract"]["qualname"]): item["contract"]
        for item in index["semantic_coverage"]
        if item["kind"] == "typescript_function_contract"
    }
    edges = contracts[("packages/fixture/src/consumer.ts", "invoke")]["caller_edges"]

    assert any(
        edge["resolution"] == "cross_file_symbol"
        and edge["target_path"] == "packages/fixture/src/library.ts"
        and edge["target_qualname"] == "execute"
        for edge in edges
    )
    assert any(
        edge["resolution"] == "cross_file_symbol"
        and edge["target_path"] == "packages/fixture/src/library.ts"
        and edge["target_qualname"] == "Engine.run"
        for edge in edges
    )
    assert any(edge["resolution"] == "unresolved_external_import" for edge in edges)
    assert any(edge["resolution"] == "dynamic_import_unresolved" for edge in edges)
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_typescript_json_config_imports_link_to_exact_config_fields_without_copying_defaults(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    source_dir = tmp_path / "packages" / "fixture" / "src"
    consumer = source_dir / "settings-consumer.ts"
    consumer.write_text(
        "import settings from '../../../config/settings.json';\n"
        "import * as settingsModule from '../../../config/settings.json';\n"
        "export function useSettings(dynamicKey: string) {\n"
        "  return settings.retry.default + settingsModule.default.retry.default + settings.retry[dynamicKey];\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path, typescript_module=compiler)
    repeated = build_source_index(tmp_path, typescript_module=compiler)
    consumer_contract = next(
        item["contract"] for item in index["semantic_coverage"]
        if item["kind"] == "typescript_function_contract"
        and item["path"] == "packages/fixture/src/settings-consumer.ts"
        and item["contract"]["qualname"] == "useSettings"
    )
    config_field = next(
        item for item in index["semantic_coverage"]
        if item["kind"] == "configuration_field"
        and item["path"] == "config/settings.json"
        and item["contract"]["field_path"] == "retry.default"
    )

    reads = consumer_contract["configuration_reads"]
    assert [
        (item["config_path"], item["field_path"], item["resolution"])
        for item in reads if item["resolution"] == "resolved_json_field"
    ] == [
        ("config/settings.json", "retry.default", "resolved_json_field"),
        ("config/settings.json", "retry.default", "resolved_json_field"),
    ]
    assert any(item["resolution"] == "dynamic_property_unresolved" for item in reads)
    assert config_field["consumers"] == [{
        "path": "packages/fixture/src/settings-consumer.ts",
        "qualname": "useSettings",
        "line": 4,
        "access": "retry.default",
    }]
    assert all("value" not in key for key in consumer_contract)
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_typescript_environment_reads_capture_static_keys_and_digest_fallbacks(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    source = tmp_path / "packages" / "fixture" / "src" / "environment.ts"
    source.write_text(
        "export function readEnvironment(dynamicName: string) {\n"
        "  const token = process.env.ATLAS_TOKEN ?? 'secret-default';\n"
        "  const flag = import.meta.env.VITE_FEATURE || 'flag-default';\n"
        "  const explicit = process.env['STATIC_KEY'] ?? 7;\n"
        "  const dynamic = process.env[dynamicName];\n"
        "  return [token, flag, explicit, dynamic];\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path, typescript_module=compiler)
    repeated = build_source_index(tmp_path, typescript_module=compiler)
    contract = next(
        item["contract"] for item in index["semantic_coverage"]
        if item["kind"] == "typescript_function_contract"
        and item["path"] == "packages/fixture/src/environment.ts"
        and item["contract"]["qualname"] == "readEnvironment"
    )
    environment_reads = [
        item for item in contract["configuration_reads"]
        if item["source_kind"] == "environment"
    ]
    assert [(item["key"], item["resolution"]) for item in environment_reads] == [
        ("ATLAS_TOKEN", "resolved_environment_key"),
        ("VITE_FEATURE", "resolved_environment_key"),
        ("STATIC_KEY", "resolved_environment_key"),
        (None, "dynamic_environment_key_unresolved"),
    ]
    fallbacks = [item["fallback_digest"] for item in environment_reads[:3]]
    assert fallbacks == [
        hashlib.sha256(b"'secret-default'").hexdigest(),
        hashlib.sha256(b"'flag-default'").hexdigest(),
        hashlib.sha256(b"7").hexdigest(),
    ]
    serialized = json.dumps(contract)
    assert "secret-default" not in serialized and "flag-default" not in serialized
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_python_environment_reads_resolve_os_aliases_and_hash_default_arguments(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    source = tmp_path / "packages" / "fixture" / "src" / "environment.py"
    source.write_text(
        "import os as operating_system\n"
        "from os import getenv as read_environment\n"
        "from os import environ as environment_map\n"
        "\n"
        "def read_environment_config(dynamic_name):\n"
        "    first = operating_system.environ.get('ATLAS_MODE', 'safe-default')\n"
        "    second = read_environment('ATLAS_REGION', 'local-default')\n"
        "    third = environment_map['STATIC_ENV']\n"
        "    dynamic = operating_system.environ[dynamic_name]\n"
        "    return first, second, third, dynamic\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)
    repeated = build_source_index(tmp_path)
    contract = next(
        item["contract"] for item in index["semantic_coverage"]
        if item["kind"] == "declaration"
        and item["path"] == "packages/fixture/src/environment.py"
        and item["contract"]["qualname"] == "read_environment_config"
    )
    reads = contract["configuration_reads"]
    assert [(item["key"], item["resolution"]) for item in reads] == [
        ("ATLAS_MODE", "resolved_environment_key"),
        ("ATLAS_REGION", "resolved_environment_key"),
        ("STATIC_ENV", "resolved_environment_key"),
        (None, "dynamic_environment_key_unresolved"),
    ]
    assert [item.get("fallback_digest") for item in reads[:2]] == [
        hashlib.sha256(b"'safe-default'").hexdigest(),
        hashlib.sha256(b"'local-default'").hexdigest(),
    ]
    serialized = json.dumps(contract)
    assert "safe-default" not in serialized and "local-default" not in serialized
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_powershell_parser_contracts_capture_function_defaults_failures_and_state(tmp_path):
    _require_audit_functions()
    if shutil.which("pwsh") is None:
        pytest.skip("PowerShell AST parser is unavailable")
    _source(tmp_path)
    script = tmp_path / "packages" / "fixture" / "src" / "runtime.ps1"
    script.write_text(
        "function Invoke-AtlasTask {\n"
        "    param([string]$Mode = 'safe-default')\n"
        "    try {\n"
        "        if ($IsWindows) { $status = 'ready' }\n"
        "        else { throw 'failed' }\n"
        "    } catch {\n"
        "        $status = 'failed'\n"
        "    } finally {\n"
        "        $phase = 'closed'\n"
        "    }\n"
        "}\n",
        encoding="utf-8",
    )
    broken = tmp_path / "packages" / "fixture" / "src" / "broken.ps1"
    broken.write_text("function Incomplete {\n  try {\n", encoding="utf-8")

    index = build_source_index(tmp_path)
    repeated = build_source_index(tmp_path)
    contract_unit = next(
        item for item in index["semantic_coverage"]
        if item["kind"] == "powershell_function_contract"
        and item["path"] == "packages/fixture/src/runtime.ps1"
        and item["contract"]["qualname"] == "Invoke-AtlasTask"
    )
    contract = contract_unit["contract"]
    assert contract["source_span"] == {"start_line": 1, "end_line": 11}
    assert contract["parameters"] == [{
        "name": "$Mode",
        "default_digest": hashlib.sha256(b"'safe-default'").hexdigest(),
    }]
    assert contract["obligations"]["exceptions"] == [
        {"kind": "throw", "line": 5},
        {"kind": "catch", "line": 6},
        {"kind": "finally", "line": 8},
    ]
    assert contract["obligations"]["platform_branches"]
    assert {item["target"] for item in contract["obligations"]["state_transitions"]} == {
        "$status", "$phase",
    }
    assert any(
        item["kind"] == "powershell_parse_error"
        and item["path"] == "packages/fixture/src/broken.ps1"
        and item["resolution"] == "UNRESOLVED"
        for item in index["semantic_coverage"]
    )
    assert "safe-default" not in json.dumps(contract)
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_shell_scripts_are_parse_only_and_other_script_languages_remain_explicitly_unresolved(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    marker = tmp_path / "should-not-exist.marker"
    valid = scripts / "valid.sh"
    valid.write_text(
        "#!/usr/bin/env bash\n"
        "run_task() {\n"
        "  if [ \"${1:-}\" = yes ]; then\n"
        f"    touch '{marker.as_posix()}'\n"
        "  else\n"
        "    \"$DYNAMIC\" arg\n"
        "  fi\n"
        "}\n",
        encoding="utf-8",
    )
    broken = scripts / "broken.sh"
    broken.write_text("#!/bin/sh\nif then\n  exit 1\nfi\n", encoding="utf-8")
    batch = scripts / "launch.cmd"
    batch.write_text("@echo off\ncall node.exe app.js\n", encoding="utf-8")
    nsis_script = scripts / "installer.nsi"
    nsis_script.write_text("OutFile \"installer.exe\"\n", encoding="utf-8")
    installer = scripts / "installer.nsh"
    installer.write_text("!macro Configure\n  DetailPrint \"configured\"\n!macroend\n", encoding="utf-8")

    index = build_source_index(tmp_path)
    repeated = build_source_index(tmp_path)
    units = index["semantic_coverage"]
    valid_contract = next(
        item["contract"] for item in units
        if item["kind"] == "shell_syntax_contract" and item["path"] == "scripts/valid.sh"
    )
    assert valid_contract["parse_status"] == "SYNTAX_VALID_SEMANTICS_UNRESOLVED"
    assert valid_contract["parser"] == "bash"
    function_contract = next(
        item for item in units
        if item["kind"] == "shell_function_contract"
        and item["path"] == "scripts/valid.sh"
        and item["symbol"] == "run_task"
    )
    assert function_contract["contract"]["source_span"] == {"start_line": 2, "end_line": 8}
    control_contract = next(
        item for item in units
        if item["kind"] == "shell_control_flow_contract"
        and item["path"] == "scripts/valid.sh"
        and item["contract"]["node_type"] == "if_statement"
    )
    assert control_contract["contract"]["source_span"] == {"start_line": 3, "end_line": 7}
    assert control_contract["resolution"] == "UNRESOLVED"
    assert any(
        item["kind"] == "shell_dynamic_command_unresolved"
        and item["path"] == "scripts/valid.sh"
        and item["resolution"] == "UNRESOLVED"
        for item in units
    )
    assert any(
        item["kind"] == "shell_parse_error"
        and item["path"] == "scripts/broken.sh"
        and item["resolution"] == "UNRESOLVED"
        and item["line"] == 2
        for item in units
    )
    for path in ("scripts/launch.cmd", "scripts/installer.nsi", "scripts/installer.nsh"):
        assert any(item["path"] == path and item["kind"] == "file_review" for item in units)
        assert any(
            item["path"] == path and item["kind"] == "script_parser_unavailable"
            and item["resolution"] == "UNRESOLVED"
            for item in units
        )
    assert not marker.exists()
    assert index["semantic_coverage"] == repeated["semantic_coverage"]


def test_shell_parse_uses_pinned_grammar_when_windows_shell_alias_returns_launcher_text(tmp_path, monkeypatch):
    assert dsh_shell_parse is not None
    (tmp_path / "valid.sh").write_text("#!/usr/bin/env bash\nif true; then echo ok; fi\n", encoding="utf-8")
    (tmp_path / "broken.sh").write_text("#!/bin/sh\nif then\n  exit 1\nfi\n", encoding="utf-8")
    monkeypatch.setattr(dsh_shell_parse.shutil, "which", lambda _name: "C:/Windows/System32/bash.EXE")

    def windows_app_execution_alias(*args, **kwargs):
        return dsh_shell_parse.subprocess.CompletedProcess(
            args=args[0], returncode=1, stdout="Windows Subsystem for Linux has no installed distributions.\n", stderr="",
        )

    monkeypatch.setattr(dsh_shell_parse.subprocess, "run", windows_app_execution_alias)
    rows = dsh_shell_parse.parse(tmp_path, ["valid.sh", "broken.sh"])

    valid, broken = rows
    assert valid["parse_diagnostics"] == []
    assert valid["contracts"][0]["parse_status"] == "SYNTAX_VALID_SEMANTICS_UNRESOLVED"
    assert any(item["kind"] == "bash_control_flow" for item in valid["contracts"])
    assert broken["parse_diagnostics"][0]["line"] == 2
    assert len(broken["parse_diagnostics"][0]["reason_digest"]) == 64


def test_shell_parser_crash_isolated_as_unresolved_for_that_file(tmp_path, monkeypatch):
    assert dsh_capability_audit is not None
    relative = "scripts/crashing.sh"

    def crash_parser(*args, **kwargs):
        return dsh_capability_audit.subprocess.CompletedProcess(
            args=args[0], returncode=3221225477, stdout="", stderr="",
        )

    monkeypatch.setattr(dsh_capability_audit.subprocess, "run", crash_parser)
    rows = dsh_capability_audit._shell_script_contracts(tmp_path, {relative: b"#!/usr/bin/env bash\n"})

    assert rows[relative]["parser_status"] == "SHELL_AST_HELPER_EXIT_3221225477"
    assert rows[relative]["diagnostic_digest"] == hashlib.sha256(b"").hexdigest()


def test_shell_parser_crash_keeps_each_nonempty_source_line_unresolved():
    assert dsh_capability_audit is not None
    source = "#!/usr/bin/env bash\n# secret-bearing comment\necho TOKEN_VALUE\n\nexit 2\n"
    parser_row = {
        "path": "scripts/crashing.sh",
        "parser_status": "SHELL_AST_HELPER_EXIT_3221225477",
    }

    units = dsh_capability_audit._semantic_units(
        "scripts/crashing.sh", source, shell_row=parser_row,
    )
    opaque = [unit for unit in units if unit["kind"] == "shell_opaque_line_unresolved"]

    assert len(opaque) == 4
    assert [unit["contract"]["source_span"]["start_line"] for unit in opaque] == [1, 2, 3, 5]
    assert all(unit["resolution"] == "UNRESOLVED" for unit in opaque)
    assert all("source_text" not in unit["contract"] for unit in opaque)
    assert "TOKEN_VALUE" not in json.dumps(units)


def test_shell_ast_keeps_error_platform_status_and_dynamic_launch_semantics_unresolved(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    script = tmp_path / "scripts" / "policy.sh"
    script.parent.mkdir()
    script.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "run_gate() {\n"
        "  trap 'cleanup' EXIT\n"
        "  if [[ \"$OSTYPE\" == linux* ]]; then\n"
        "    exec \"$GATE_BIN\" --check\n"
        "  fi\n"
        "  return 2\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)
    units = [item for item in index["semantic_coverage"] if item["path"] == "scripts/policy.sh"]

    assert any(item["kind"] == "shell_error_policy_contract" for item in units)
    assert any(item["kind"] == "shell_trap_contract" and item["resolution"] == "UNRESOLVED" for item in units)
    assert any(item["kind"] == "shell_platform_condition_contract" for item in units)
    assert any(item["kind"] == "shell_dynamic_launch_unresolved" for item in units)
    assert any(
        item["kind"] == "shell_status_transition_contract"
        and item["contract"].get("status") == 2
        for item in units
    )


def test_static_script_invocation_edges_resolve_package_and_workflow_entrypoints(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    package_json = tmp_path / "packages" / "fixture" / "package.json"
    manifest = json.loads(package_json.read_text(encoding="utf-8"))
    manifest["scripts"] = {"check:worker": "bash scripts/worker.sh"}
    package_json.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    worker = package_json.parent / "scripts" / "worker.sh"
    worker.parent.mkdir()
    worker.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    workflow = tmp_path / ".github" / "workflows" / "ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n  check:\n    steps:\n"
        "      - run: sh scripts/ci-check.sh\n"
        "      - run: packages/fixture/scripts/worker.sh\n",
        encoding="utf-8",
    )
    ci_script = tmp_path / "scripts" / "ci-check.sh"
    ci_script.parent.mkdir()
    ci_script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    index = build_source_index(tmp_path)
    edges = [item for item in index["semantic_coverage"] if item["kind"] == "script_invocation_edge"]

    assert any(
        edge["path"] == "packages/fixture/package.json"
        and edge["contract"].get("target_path") == "packages/fixture/scripts/worker.sh"
        and edge["contract"].get("target_exists") is True
        for edge in edges
    )
    assert any(
        edge["path"] == ".github/workflows/ci.yml"
        and edge["contract"].get("target_path") == "scripts/ci-check.sh"
        and edge["contract"].get("target_exists") is True
        for edge in edges
    )
    assert any(
        edge["path"] == ".github/workflows/ci.yml"
        and edge["contract"].get("launcher") == "direct"
        and edge["contract"].get("target_path") == "packages/fixture/scripts/worker.sh"
        for edge in edges
    )
    assert all(edge["resolution"] == "UNRESOLVED" for edge in edges)


def test_windows_batch_contracts_capture_state_and_dynamic_targets_without_values():
    assert dsh_capability_audit is not None
    source = (
        "@echo off\n"
        "setlocal EnableExtensions\n"
        "set \"INSTALL_ROOT=%~dp0..\"\n"
        "if errorlevel 1 exit /b %errorlevel%\n"
        "call \"%INSTALL_ROOT%\\common.cmd\"\n"
    )

    units = dsh_capability_audit._semantic_units("scripts/setup.cmd", source)
    contracts = [unit for unit in units if unit["kind"].startswith("windows_batch_")]
    serialized = json.dumps(contracts)

    assert any(unit["kind"] == "windows_batch_scope" and unit["line"] == 2 for unit in contracts)
    assert any(unit["kind"] == "windows_batch_assignment" and unit["line"] == 3 for unit in contracts)
    assert any(unit["kind"] == "windows_batch_control_flow" and unit["line"] == 4 for unit in contracts)
    assert any(unit["kind"] == "windows_batch_dynamic_target" and unit["line"] == 5 for unit in contracts)
    assert all(unit["resolution"] == "UNRESOLVED" for unit in contracts)
    assert "INSTALL_ROOT=%~dp0" not in serialized
    assert "%INSTALL_ROOT%" not in serialized


def test_nsis_contracts_capture_include_function_macro_branch_and_install_state(tmp_path):
    assert dsh_capability_audit is not None
    source = (
        '!include "common.nsh"\n'
        '!define OUTPUT "$PLUGINSDIR\\probe.log"\n'
        '!ifdef ALL_USERS\n'
        'Function InstallUser\n'
        '  StrCpy $0 "private-value"\n'
        '  WriteRegStr HKCU "Software\\Fixture" "Root" "$INSTDIR"\n'
        'FunctionEnd\n'
        '!else\n'
        '!macro RemoveFixture\n'
        '  Delete "$INSTDIR\\fixture.dat"\n'
        '!macroend\n'
        '!insertmacro SharedSetup\n'
        '!endif\n'
    )
    contents = {
        "apps/installer/main.nsi": source.encode("utf-8"),
        "apps/installer/common.nsh": b"!macro SharedSetup\n!macroend\n",
    }

    units = dsh_capability_audit._semantic_units("apps/installer/main.nsi", source)
    edges = dsh_capability_audit._script_invocation_units(contents)
    contracts = [unit for unit in units if unit["kind"].startswith("nsis_")]
    serialized = json.dumps(contracts)

    assert any(unit["kind"] == "nsis_include" and unit["line"] == 1 for unit in contracts)
    assert any(unit["kind"] == "nsis_conditional" and unit["line"] == 3 for unit in contracts)
    assert any(unit["kind"] == "nsis_function" and unit["line"] == 4 for unit in contracts)
    assert any(unit["kind"] == "nsis_macro" and unit["line"] == 9 for unit in contracts)
    assert any(unit["kind"] == "nsis_install_state" and unit["line"] == 6 for unit in contracts)
    include = next(edge for edge in edges if edge["kind"] == "nsis_include_edge")
    assert include["contract"]["target_path"] == "apps/installer/common.nsh"
    assert include["contract"]["target_exists"] is True
    assert include["resolution"] == "UNRESOLVED"
    macro_edge = next(edge for edge in edges if edge["kind"] == "nsis_macro_invocation_edge")
    assert macro_edge["contract"]["macro_name"] == "SharedSetup"
    assert macro_edge["contract"]["target_paths"] == ["apps/installer/common.nsh"]
    assert macro_edge["resolution"] == "UNRESOLVED"
    assert all(unit["resolution"] == "UNRESOLVED" for unit in contracts)
    assert "private-value" not in serialized


def test_windows_script_invocation_edges_cover_cmd_and_nsis_include(tmp_path):
    assert dsh_capability_audit is not None
    contents = {
        "packages/fixture/package.json": json.dumps({
            "scripts": {"sign-win": "cmd /c scripts/windows-sign.cmd"},
        }).encode("utf-8"),
        "packages/fixture/scripts/windows-sign.cmd": b"@echo off\nexit /b 0\n",
        "apps/installer/main.nsi": b'!include "shared.nsh"\n!insertmacro SharedSetup\n',
        "apps/installer/shared.nsh": b"!macro SharedSetup\n!macroend\n",
    }

    edges = dsh_capability_audit._script_invocation_units(contents)

    cmd_edge = next(edge for edge in edges if edge["path"].endswith("package.json"))
    include_edge = next(edge for edge in edges if edge["kind"] == "nsis_include_edge")
    macro_edge = next(edge for edge in edges if edge["kind"] == "nsis_macro_invocation_edge")
    assert cmd_edge["contract"]["launcher"] == "cmd"
    assert cmd_edge["contract"]["target_path"] == "packages/fixture/scripts/windows-sign.cmd"
    assert cmd_edge["contract"]["target_exists"] is True
    assert include_edge["contract"]["target_path"] == "apps/installer/shared.nsh"
    assert include_edge["contract"]["target_exists"] is True
    assert macro_edge["contract"]["target_paths"] == ["apps/installer/shared.nsh"]
    assert all(edge["resolution"] == "UNRESOLVED" for edge in edges)


def test_typescript_syntax_diagnostics_remain_unresolved(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    broken = tmp_path / "packages" / "fixture" / "src" / "broken.ts"
    broken.write_text("const incomplete: = 1;\n", encoding="utf-8")

    index = build_source_index(tmp_path, typescript_module=compiler)

    diagnostics = [
        item for item in index["semantic_coverage"]
        if item["path"].endswith("broken.ts") and item["kind"] == "typescript_parse_error"
    ]
    assert diagnostics
    assert all(item["resolution"] == "UNRESOLVED" for item in diagnostics)


def test_typescript_contract_tracks_try_finally_await_and_promise_error_paths(tmp_path):
    _require_audit_functions()
    compiler = _typescript_compiler()
    if compiler is None:
        pytest.skip("pinned DSH TypeScript compiler is unavailable")
    _source(tmp_path)
    fixture = tmp_path / "packages" / "fixture" / "src" / "error-flow.ts"
    fixture.write_text(
        "export async function runWithCleanup(shouldFail: boolean): Promise<string> {\n"
        "  try {\n"
        "    const value = await loadValue();\n"
        "    if (shouldFail) throw new Error('do-not-copy-error-value');\n"
        "    return value;\n"
        "  } catch (error: unknown) {\n"
        "    return await Promise.reject(error);\n"
        "  } finally {\n"
        "    await releaseHandle();\n"
        "  }\n"
        "}\n"
        "export function forwardRejection(): Promise<string> {\n"
        "  return Promise.resolve('ok')\n"
        "    .catch((error) => Promise.reject(error))\n"
        "    .finally(() => releaseHandle());\n"
        "}\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path, typescript_module=compiler)
    unit = next(
        item for item in index["semantic_coverage"]
        if item["path"] == "packages/fixture/src/error-flow.ts"
        and item["kind"] == "typescript_function_contract"
        and item["contract"]["qualname"] == "runWithCleanup"
    )
    contracts = [
        item for item in index["semantic_coverage"]
        if item["path"] == "packages/fixture/src/error-flow.ts"
        and item["kind"] == "typescript_function_contract"
    ]
    serialized = json.dumps(contracts)

    assert unit["resolution"] == "UNRESOLVED"
    assert len(unit["contract"]["obligations"]["exception_scopes"]) == 1
    scope = unit["contract"]["obligations"]["exception_scopes"][0]
    assert scope["catch_span"] == {"start_line": 6, "end_line": 8}
    assert scope["finally_span"] == {"start_line": 8, "end_line": 10}
    assert len(unit["contract"]["obligations"]["await_error_sites"]) == 3
    paths = [edge["kind"] for unit in contracts
             for edge in unit["contract"]["obligations"]["promise_error_paths"]]
    assert paths.count("promise_reject") == 2
    assert paths.count("promise_catch_candidate") == 1
    assert paths.count("promise_finally_candidate") == 1
    assert "do-not-copy-error-value" not in serialized
    assert all(item["resolution"] == "UNRESOLVED" for item in contracts)


def test_python_contract_tracks_raise_except_star_finally_await_and_async_with(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    fixture = tmp_path / "packages" / "fixture" / "src" / "error_flow.py"
    fixture.write_text(
        "async def run(resource):\n"
        "    try:\n"
        "        async with resource as handle:\n"
        "            await handle.read()\n"
        "            raise OSError('do-not-copy-python-error')\n"
        "    except* ValueError as group:\n"
        "        raise RuntimeError('wrapped') from group\n"
        "    finally:\n"
        "        await resource.close()\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)
    unit = next(
        item for item in index["semantic_coverage"]
        if item["path"] == "packages/fixture/src/error_flow.py"
        and item["kind"] == "declaration"
        and item["symbol"] == "run"
    )
    contract = unit["contract"]
    serialized = json.dumps(contract)

    assert unit["resolution"] == "UNRESOLVED"
    assert len(contract["obligations"]["exception_scopes"]) == 1
    scope = contract["obligations"]["exception_scopes"][0]
    assert scope["try_span"] == {"start_line": 3, "end_line": 5}
    assert scope["handlers"][0]["handler_kind"] == "except_star"
    assert scope["finally_span"] == {"start_line": 9, "end_line": 9}
    assert [item["line"] for item in contract["obligations"]["raises"]] == [5, 7]
    assert contract["obligations"]["raises"][1]["cause_digest"] is not None
    assert len(contract["obligations"]["await_error_sites"]) == 2
    assert contract["obligations"]["resource_scopes"][0]["kind"] == "async_with"
    assert "do-not-copy-python-error" not in serialized


def test_missing_typescript_compiler_creates_unresolved_contract_record(tmp_path, monkeypatch):
    _require_audit_functions()
    monkeypatch.delenv("ATLAS_DSH_TYPESCRIPT_MODULE", raising=False)
    _source(tmp_path)

    index = build_source_index(tmp_path, typescript_module=tmp_path / "missing" / "typescript.js")

    missing = [
        item for item in index["semantic_coverage"]
        if item["path"].endswith("index.ts") and item["kind"] == "typescript_parser_unavailable"
    ]
    assert missing
    assert all(item["resolution"] == "UNRESOLVED" for item in missing)
    assert all(item["contract"]["parse_status"] == "UNRESOLVED" for item in missing)


def test_toml_configuration_fields_are_indexed_without_copying_values(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    config = tmp_path / "config" / "runtime.toml"
    config.write_text(
        "[retry]\n"
        "max_attempts = 4\n"
        "wait_seconds = 0.5\n"
        "[approval]\n"
        "mode = 'ask'\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)

    fields = [
        item for item in index["semantic_coverage"]
        if item["path"] == "config/runtime.toml" and item["kind"] == "configuration_field"
    ]
    by_path = {item["contract"]["field_path"]: item for item in fields}
    assert set(by_path) == {"retry.max_attempts", "retry.wait_seconds", "approval.mode"}
    assert by_path["retry.max_attempts"]["contract"]["source_line"] == 2
    assert by_path["retry.max_attempts"]["contract"]["value_type"] == "integer"
    assert by_path["retry.max_attempts"]["contract"]["value_digest"]
    assert "default_value" not in by_path["retry.max_attempts"]["contract"]
    assert all(item["resolution"] == "UNRESOLVED" for item in fields)


def test_yaml_configuration_fields_keep_nested_paths_and_source_lines(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    config = tmp_path / "config" / "runtime.yaml"
    config.write_text(
        "retry:\n"
        "  max_attempts: 4\n"
        "approval:\n"
        "  mode: ask\n"
        "plugins:\n"
        "  - name: alpha\n"
        "    enabled: true\n"
        "  - name: beta\n"
        "    enabled: false\n",
        encoding="utf-8",
    )

    index = build_source_index(tmp_path)

    fields = [
        item for item in index["semantic_coverage"]
        if item["path"] == "config/runtime.yaml" and item["kind"] == "configuration_field"
    ]
    by_path = {item["contract"]["field_path"]: item for item in fields}
    assert set(by_path) == {
        "retry.max_attempts", "approval.mode",
        "plugins.0.name", "plugins.0.enabled", "plugins.1.name", "plugins.1.enabled",
    }
    assert by_path["retry.max_attempts"]["line"] == 2
    assert by_path["approval.mode"]["line"] == 4


def test_check_rejects_new_manifest_and_component_without_package_declaration(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    baseline = build_source_index(tmp_path)
    second = tmp_path / "packages" / "new-component"
    second.mkdir(parents=True)
    (second / "package.json").write_text(json.dumps({"name": "@fixture/new"}), encoding="utf-8")

    findings = check_source_index(tmp_path, baseline)

    assert any(item["code"] == "SOURCE_FILE_ADDED" and item["path"].endswith("package.json")
               for item in findings)


def test_check_rejects_index_built_by_stale_extractor(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    baseline = build_source_index(tmp_path)
    baseline["extractor_version"] -= 1

    findings = check_source_index(tmp_path, baseline)

    assert any(item["code"] == "EXTRACTOR_VERSION_MISMATCH" for item in findings)


def test_scan_is_byte_stable_for_the_same_source(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    # Production keeps the audit ledger outside the DSH checkout.  If the
    # fixture places it under the scanned root, the second scan correctly sees
    # the newly-created ledger as additional source files.
    ledger = tmp_path.parent / f"{tmp_path.name}-ledger"

    scan_to_ledger(tmp_path, ledger)
    first = (ledger / "source-index.json").read_bytes()
    scan_to_ledger(tmp_path, ledger)

    assert (ledger / "source-index.json").read_bytes() == first


def test_scan_refreshes_obligation_counts_without_marking_global_completion(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    ledger = tmp_path.parent / f"{tmp_path.name}-ledger"
    ledger.mkdir()
    (ledger / "completion.json").write_text(json.dumps({
        "schema_version": 1,
        "status": "INCOMPLETE",
        "counts": {},
        "source_obligations": {"total": 1, "unresolved": 1},
    }), encoding="utf-8")

    index = scan_to_ledger(tmp_path, ledger)
    completion = json.loads((ledger / "completion.json").read_text(encoding="utf-8"))

    assert completion["source_obligations"]["total"] == index["summary"]["semantic_unit_count"]
    assert completion["source_obligations"]["unresolved"] == index["summary"]["unresolved_semantic_unit_count"]
    assert completion["status"] == "INCOMPLETE"


def test_check_rejects_unresolved_units_dangling_references_and_false_closed(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    index = build_source_index(tmp_path)
    atomics = [{
        "atomic_id": "A-1",
        "implementation_status": "CLOSED",
        "evidence_status": "NONE",
        "source_units": ["missing-unit"],
    }]

    findings = check_source_index(tmp_path, index, atomic_rows=atomics)

    codes = {item["code"] for item in findings}
    assert "SEMANTIC_UNIT_UNRESOLVED" in codes
    assert "REFERENCE_MISSING" in codes
    assert "FALSE_CLOSED" in codes


def test_check_rejects_unmapped_package_entry_points(tmp_path):
    _require_audit_functions()
    _source(tmp_path)
    index = build_source_index(tmp_path)
    atomics = [{"atomic_id": "PACKAGE-EXPORT"}]

    entry = next(item for item in index["entry_points"] if item["kind"] == "package_exports")
    findings = check_source_index(tmp_path, index, atomic_rows=atomics)

    assert entry["resolution"] == "UNRESOLVED"
    assert any(
        item["code"] == "ENTRY_POINT_UNRESOLVED" and item["entry_id"] == entry["entry_id"]
        for item in findings
    )

    entry["resolution"] = "MAPPED"
    entry["atomic_ids"] = ["PACKAGE-EXPORT"]
    findings = check_source_index(tmp_path, index, atomic_rows=atomics)
    assert not any(
        item.get("entry_id") == entry["entry_id"]
        and item["code"] in {"ENTRY_POINT_UNRESOLVED", "ENTRY_POINT_MAPPING_EMPTY", "REFERENCE_MISSING"}
        for item in findings
    )

    entry["atomic_ids"] = ["MISSING-ATOMIC"]
    findings = check_source_index(tmp_path, index, atomic_rows=atomics)
    assert any(
        item["code"] == "REFERENCE_MISSING" and item.get("entry_id") == entry["entry_id"]
        for item in findings
    )

    entry["atomic_ids"] = []
    entry["interaction_ids"] = ["EDGE-ENTRY-CONSUMER"]
    edges = [{"edge_id": "EDGE-ENTRY-CONSUMER", "from": "package export", "to": "consumer"}]
    findings = check_source_index(tmp_path, index, atomic_rows=atomics, interaction_rows=edges)
    assert not any(
        item.get("entry_id") == entry["entry_id"] and item["code"] == "REFERENCE_MISSING"
        for item in findings
    )


def test_scan_applies_semantic_decisions_and_rejects_stale_source_digest(tmp_path):
    _require_audit_functions()
    source = tmp_path / "source"
    ledger = tmp_path / "ledger"
    _source(source)
    ledger.mkdir()

    original = build_source_index(source)
    unit = next(item for item in original["semantic_coverage"] if item["kind"] == "file_review")
    (ledger / "atomic-capabilities.jsonl").write_text(
        json.dumps({"atomic_id": "FIXTURE-SEMANTIC-ATOM"}) + "\n", encoding="utf-8",
    )
    (ledger / "interaction-edges.jsonl").write_text(
        json.dumps({"edge_id": "EDGE-FIXTURE-SEMANTIC"}) + "\n", encoding="utf-8",
    )
    decision = {
        "schema_version": 1,
        "source_head": original["source"]["head"],
        "unit_id": unit["unit_id"],
        "digest": unit["digest"],
        "resolution": "MAPPED",
        "atomic_ids": ["FIXTURE-SEMANTIC-ATOM"],
        "interaction_ids": ["EDGE-FIXTURE-SEMANTIC"],
        "evidence": ["Reviewed fixture function against its provider-consumer contract."],
    }
    (ledger / "semantic-decisions.jsonl").write_text(
        json.dumps(decision) + "\n", encoding="utf-8",
    )

    scanned = scan_to_ledger(source, ledger)
    mapped = next(item for item in scanned["semantic_coverage"] if item["unit_id"] == unit["unit_id"])
    assert mapped["resolution"] == "MAPPED"
    assert mapped["atomic_ids"] == ["FIXTURE-SEMANTIC-ATOM"]
    assert mapped["interaction_ids"] == ["EDGE-FIXTURE-SEMANTIC"]
    assert mapped["evidence"] == decision["evidence"]
    assert scanned["summary"]["unresolved_semantic_unit_count"] == len(scanned["semantic_coverage"]) - 1

    index_path = ledger / "source-index.json"
    indexed_before_stale_scan = index_path.read_text(encoding="utf-8")
    source_file = source / unit["path"]
    source_file.write_text(source_file.read_text(encoding="utf-8").replace('"default": 3', '"default": 4'),
                           encoding="utf-8")
    with pytest.raises(ValueError, match="stale semantic decision"):
        scan_to_ledger(source, ledger)
    assert index_path.read_text(encoding="utf-8") == indexed_before_stale_scan


def test_scan_rejects_unowned_semantic_decision_references(tmp_path):
    _require_audit_functions()
    source = tmp_path / "source"
    ledger = tmp_path / "ledger"
    _source(source)
    ledger.mkdir()
    index = build_source_index(source)
    unit = next(item for item in index["semantic_coverage"] if item["kind"] == "export")
    decision = {
        "schema_version": 1,
        "source_head": index["source"]["head"],
        "unit_id": unit["unit_id"],
        "digest": unit["digest"],
        "resolution": "MAPPED",
        "atomic_ids": ["MISSING-ATOMIC"],
        "interaction_ids": [],
        "evidence": ["The mapped source unit must point at an existing atomic ledger row."],
    }
    (ledger / "semantic-decisions.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing atomic row"):
        scan_to_ledger(source, ledger)

    decision["unit_id"] = "DSH-UNKNOWN-UNIT"
    decision["atomic_ids"] = []
    decision["interaction_ids"] = ["EDGE-UNKNOWN"]
    (ledger / "interaction-edges.jsonl").write_text(
        json.dumps({"edge_id": "EDGE-UNKNOWN"}) + "\n", encoding="utf-8",
    )
    (ledger / "semantic-decisions.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown unit"):
        scan_to_ledger(source, ledger)


def _require_runner_functions():
    assert callable(run_command) and callable(signal_if_same_process), (
        "the bounded validation runner is not implemented yet"
    )


def test_validation_runner_captures_output_and_natural_exit(tmp_path):
    _require_runner_functions()
    script = tmp_path / "success.py"
    script.write_text("print('finished', flush=True)\n", encoding="utf-8")

    result = run_command(
        [sys.executable, str(script)], cwd=tmp_path, log_dir=tmp_path / "logs",
        timeout_seconds=5,
    )

    assert result["status"] == "PASS"
    assert result["returncode"] == 0
    assert Path(result["stdout_path"]).read_text(encoding="utf-8").strip() == "finished"
    assert Path(result["stderr_path"]).read_text(encoding="utf-8") == ""


def test_validation_runner_preserves_output_when_process_hangs_after_write(tmp_path):
    _require_runner_functions()
    script = tmp_path / "hang.py"
    script.write_text(
        "import time\nprint('marker-before-hang', flush=True)\ntime.sleep(30)\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, str(script)], cwd=tmp_path, log_dir=tmp_path / "logs",
        timeout_seconds=0.5, cleanup_seconds=1.5,
    )

    assert result["status"] == "TIMEOUT"
    assert "marker-before-hang" in Path(result["stdout_path"]).read_text(encoding="utf-8")
    assert result["leftover_processes"] == []


def test_validation_runner_cleans_owned_child_after_parent_hangs(tmp_path):
    _require_runner_functions()
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    receipt = tmp_path / "child.json"
    child.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
    parent.write_text(
        "import json, pathlib, subprocess, sys, time, psutil\n"
        f"child = subprocess.Popen([sys.executable, {str(child)!r}])\n"
        "identity = {'pid': child.pid, 'created_at': psutil.Process(child.pid).create_time()}\n"
        f"pathlib.Path({str(receipt)!r}).write_text(json.dumps(identity))\n"
        "print('child-started', flush=True)\ntime.sleep(30)\n",
        encoding="utf-8",
    )

    result = run_command(
        [sys.executable, str(parent)], cwd=tmp_path, log_dir=tmp_path / "logs",
        timeout_seconds=0.7, cleanup_seconds=1.5,
    )

    assert result["status"] == "TIMEOUT"
    assert result["leftover_processes"] == []
    identity = json.loads(receipt.read_text(encoding="utf-8"))
    import psutil
    try:
        child_process = psutil.Process(identity["pid"])
        same_process_alive = (
            child_process.is_running()
            and child_process.create_time() == identity["created_at"]
        )
    except psutil.NoSuchProcess:
        same_process_alive = False
    assert same_process_alive is False


def test_validation_runner_does_not_signal_a_reused_pid(monkeypatch):
    _require_runner_functions()
    import psutil

    class ReusedProcess:
        terminated = False
        killed = False

        def create_time(self):
            return 200.0

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

    process = ReusedProcess()
    monkeypatch.setattr(psutil, "Process", lambda _pid: process)

    result = signal_if_same_process(ProcessIdentity(pid=4242, created_at=100.0), force=True)

    assert result == "pid_reused"
    assert process.terminated is False
    assert process.killed is False
