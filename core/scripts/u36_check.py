"""U36 acceptance scenarios. No Electron process or screenshots are used."""

from __future__ import annotations

import ast
import base64
import io
import json
import importlib.metadata
import os
import re
import subprocess
import sys
import tempfile
import tomllib
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "core"
sys.path.insert(0, str(CORE))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def scenario(name: str, fn) -> None:
    print(f"U36 scenario: {name}", flush=True)
    fn()
    print(f"U36 scenario PASS: {name}", flush=True)


def real_ocr_scenario() -> None:
    from PIL import Image, ImageDraw, ImageFont

    from atlas.runtime.media_understanding import ocr_image_data_url

    image = Image.new("RGB", (1500, 420), "white")
    draw = ImageDraw.Draw(image)
    fonts = [Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")]
    font_path = next((path for path in fonts if path.is_file()), None)
    check(font_path is not None, "Windows Chinese test font is unavailable")
    font = ImageFont.truetype(str(font_path), 64)
    draw.text((36, 45), "Atlas OCR Check 4729", fill="black", font=font)
    draw.text((36, 210), "本地文字识别验证 5831", fill="black", font=font)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    payload = base64.b64encode(buffer.getvalue()).decode("ascii")
    text, audit = ocr_image_data_url(f"data:image/png;base64,{payload}", 0)
    check(audit.get("status") == "complete", f"RapidOCR did not complete: {audit}")
    check(audit.get("extractor") == "rapidocr-onnxruntime", f"unexpected OCR engine: {audit}")
    check(audit.get("sha256") and audit.get("characters", 0) > 0,
          "OCR source audit is incomplete")
    check("4729" in text and "5831" in text and any("文" in char for char in text),
          f"synthetic multilingual OCR returned unexpected text: {text!r}")


def dependency_and_cron_scenario() -> None:
    project = tomllib.loads((CORE / "pyproject.toml").read_text(encoding="utf-8"))
    required = project["project"].get("dependencies", [])
    optional = project["project"].get("optional-dependencies", {})
    declared = set()
    for item in [*required, *(value for values in optional.values() for value in values)]:
        match = re.match(r"\s*([A-Za-z0-9_.-]+)", item)
        if match:
            declared.add(match.group(1).lower().replace("_", "-"))
        direct = re.match(r"\s*([A-Za-z0-9_.-]+)\s*@", item)
        if direct:
            declared.add(direct.group(1).lower().replace("_", "-"))
    aliases = {
        "PIL": "pillow", "yaml": "pyyaml", "cv2": "opencv-python", "fitz": "pymupdf",
        "bs4": "beautifulsoup4", "dotenv": "python-dotenv", "sklearn": "scikit-learn",
        "winpty": "pywinpty", "skillopt_sleep": "skillopt", "google": "google-generativeai",
        "anthropic": "anthropic", "charset_normalizer": "charset-normalizer",
        "rapidocr_onnxruntime": "rapidocr-onnxruntime",
        "daytona": "daytona", "modal": "modal", "vercel": "vercel",
        "skillopt_sleep": "skillopt",
    }
    distributions = importlib.metadata.packages_distributions()
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    third_party: set[str] = set()
    for path in (CORE / "atlas").rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise AssertionError(f"cannot scan import declarations in {path}: {exc}") from exc
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.append(node.module.split(".", 1)[0])
            for name in names:
                if name in stdlib or name == "atlas" or name.startswith("_"):
                    continue
                third_party.add(name)
    undeclared = []
    for name in sorted(third_party):
        matches = {item.lower().replace("_", "-") for item in distributions.get(name, [])}
        alias = aliases.get(name)
        if alias:
            matches.add(alias.lower().replace("_", "-"))
        if not matches.intersection(declared):
            undeclared.append(name)
    check(not undeclared, f"core/atlas has undeclared top-level imports: {undeclared}")
    from atlas.automation.engine import compute_next_run_at

    next_run = compute_next_run_at({"trigger": {
        "kind": "cron", "cron_expr": "0 0 9 * * *", "tz": "UTC",
    }}, from_time=datetime(2026, 10, 25, 8, 0, tzinfo=UTC))
    check(next_run == "2026-10-25T09:00:00+00:00", f"cron next_run_at is wrong: {next_run}")
    from importlib import import_module

    import_module("croniter")

    print(f"  scanned {len(third_party)} third-party top-level imports; none undeclared", flush=True)


def pytest_scenario(*nodeids: str) -> None:
    env = dict(os.environ)
    env.setdefault("ATLAS_ROOT", r"C:\engine-reg\_atlasroot")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *nodeids, "-q"], cwd=ROOT,
        env=env, check=False, encoding="utf-8", errors="replace",
    )
    check(result.returncode == 0, f"pytest scenario failed: {' '.join(nodeids)}")


def cli_contract_scenario() -> None:
    from atlas.cli_events import ExecJSONLStream
    from atlas.cli_notifications import emit_cli_notification

    with tempfile.TemporaryDirectory(prefix="atlas-u36-notify-") as directory:
        target = Path(directory) / "notifications.jsonl"
        os.environ["ATLAS_SECRET_TEST"] = "must-not-cross-process"
        source = (
            "import json, os, sys; "
            "open(sys.argv[1], 'a', encoding='utf-8').write(json.dumps({"
            "'status':sys.argv[2], 'secret':os.getenv('ATLAS_SECRET_TEST')})+'\\n')"
        )
        command = [sys.executable, "-c", source, str(target)]
        for status in ("completed", "failed", "cancelled"):
            check(emit_cli_notification(status, mode="off", command=command),
                  f"CLI notification failed for {status}")
        os.environ.pop("ATLAS_SECRET_TEST", None)
        rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines()]
        check([row["status"] for row in rows] == ["completed", "failed", "cancelled"],
              "CLI notification child received incomplete status sequence")
        check(all(row["secret"] is None for row in rows),
              "CLI notification child inherited a parent secret")
    output = io.StringIO()
    stream = ExecJSONLStream("u36-session", output)
    stream.emit("turn.started")
    item = stream.start_item("assistant", role="assistant")
    stream.emit("text.delta", item_id=item, text="OK")
    stream.complete_item(item, "assistant", text="OK")
    stream.emit("turn.completed")
    stream.emit("end", status="completed")
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    check([event["sequence"] for event in events] == list(range(1, len(events) + 1)),
          "JSONL event sequence is not monotonic")
    check(len({event["event_id"] for event in events}) == len(events),
          "JSONL event ids are not unique")
    check(all(event["protocol"] == "atlas.exec.events" and event["version"] == 1
              for event in events), "JSONL protocol envelope is missing")
    check(events[-1]["type"] == "end" and events[-1]["status"] == "completed",
          "JSONL stream did not close with a completed status")


def main() -> int:
    sys.path.insert(0, str(CORE / "atlas"))
    scenario("0a synthetic Chinese and English text through real cached RapidOCR", real_ocr_scenario)
    scenario("0b croniter next-run calculation and full third-party import declaration scan",
             dependency_and_cron_scenario)
    scenario("1 and 2 CLI status-only notifications and versioned JSONL event lifecycles",
             cli_contract_scenario)
    scenario("3 isolated code-mode batch and full current-tool dispatch", lambda:
             pytest_scenario(
                 "core/tests/test_agent_enrichment.py::test_codeact_subprocess_uses_atlas_bridge_for_three_operations",
                 "core/tests/test_agent_enrichment.py::test_execute_code_dispatches_through_current_agent_tool_pipeline",
             ))
    scenario("4 automatic run learning, conversation extraction, approval, rollback, Agent/project loading", lambda:
             pytest_scenario(
                 "core/tests/test_evolution_run_learning.py",
                 "core/tests/test_evolution_skill_curator.py::test_conversation_extraction_approval_and_rollback_route",
                 "core/tests/test_project_skill_settings.py",
             ))
    print("Electron was not started; no screenshots were captured.", flush=True)
    print("U36 CHECK PASS", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
