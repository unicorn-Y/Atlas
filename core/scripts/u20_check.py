"""U20 end-to-end checks. Uses the configured Atlas model for the repository-review pass."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def check_repository_review(base: Path) -> None:
    from atlas.review.engine import collect_repository_context, merge_layer_findings, register_review_routes, run_repository_review_sync
    from fastapi import FastAPI
    from atlas.cli import main
    from click.testing import CliRunner

    repo = base / "review-repo"
    repo.mkdir()
    import subprocess
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (repo / "sample.py").write_text("def ratio(value, divisor):\n    return value / divisor\n", encoding="utf-8")
    (repo / "README.md").write_text("Review fixture\n", encoding="utf-8")
    (repo / "settings.py").write_text('api_key = "u20-secret-value-do-not-send"\n', encoding="utf-8")
    (repo / ".env").write_text("DEEPSEEK_API_KEY=local-only-not-for-context\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "local-state.json").write_text('{"token":"runtime-private"}\n', encoding="utf-8")
    context = collect_repository_context(str(repo))
    assert context["file_count"] >= 4 and "sample.py" in context["source"]
    assert ".env" not in context["inventory"] and "u20-secret-value-do-not-send" not in context["source"]
    assert not any(item.startswith("data/") for item in context["inventory"])
    merged = merge_layer_findings({
        "correctness": [{"file": "sample.py", "line": 2, "severity": "major", "title": "Division by zero", "explanation": "No guard", "evidence": "return value / divisor", "review_layer": "correctness"}],
        "security": [{"file": "sample.py", "line": 2, "severity": "major", "title": "Division by zero risk", "explanation": "No guard", "evidence": "return value / divisor", "review_layer": "security"}],
    })
    assert len(merged) == 1 and set(merged[0]["review_layers"]) == {"correctness", "security"}
    model = os.environ.get("U20_REVIEW_MODEL", "deepseek-v4.1-flash")
    report = run_repository_review_sync(str(repo), model=model)
    assert len(report["review_layers"]) == 3, f"parallel review layers failed: {report['layer_errors']}"
    assert report["scope"] == "repository" and isinstance(report["findings"], list)
    print(f"repository review: live {model}, {len(report['review_layers'])}/3 layers, {len(report['findings'])} findings")
    cli_report = {"scope": "repository", "file_count": 4, "review_layers": ["correctness", "security", "architecture"], "findings": [], "layer_errors": {}}
    with patch("atlas.review.engine.run_repository_review_sync", return_value=cli_report):
        output = base / "cli-review.json"
        result = CliRunner().invoke(main, ["review", "--workspace", str(repo), "--ci", "--json", "--output", str(output)])
        assert result.exit_code == 0 and json.loads(output.read_text(encoding="utf-8"))["scope"] == "repository", result.output
    app = FastAPI(); register_review_routes(app)
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/review/repository")
    class RequestFixture:
        async def json(self): return {"workspace": str(repo)}
    with patch("atlas.review.engine.run_repository_review_sync", return_value=cli_report):
        api_report = asyncio.run(endpoint(RequestFixture()))
    assert api_report["scope"] == "repository"


def check_github_workflow(base: Path) -> None:
    from atlas.github_workflows import install_workflow, workflow_preview
    from click.testing import CliRunner
    from atlas.cli import main
    repo = base / "workflow-repo"
    (repo / ".git").mkdir(parents=True)
    preview = workflow_preview(repo, "atlas-review")
    assert preview["exists"] is False and "DEEPSEEK_API_KEY" in str(preview["secret"])
    destination = install_workflow(repo, "atlas-review")
    body = destination.read_text(encoding="utf-8")
    assert "atlas review --ci" in body and "contents: read" in body
    try:
        install_workflow(repo, "atlas-review")
    except FileExistsError:
        pass
    else:
        raise AssertionError("existing workflow was overwritten without an explicit choice")
    replaced = install_workflow(repo, "python-checks", overwrite=True)
    assert replaced.exists() and "Python checks" in replaced.read_text(encoding="utf-8")
    cli_repo = base / "cli-workflow-repo"
    (cli_repo / ".git").mkdir(parents=True)
    cancelled = CliRunner().invoke(main, ["github", "install-workflow", "--workspace", str(cli_repo), "--template", "atlas-review"], input="n\n")
    assert cancelled.exit_code == 0 and "即将写入的 workflow" in cancelled.output
    assert not (cli_repo / ".github/workflows/atlas-review.yml").exists()
    result = CliRunner().invoke(main, ["github", "install-workflow", "--workspace", str(cli_repo), "--template", "atlas-review", "--yes"])
    assert result.exit_code == 0 and "所需 GitHub Actions 权限" in result.output and (cli_repo / ".github/workflows/atlas-review.yml").exists(), result.output
    assert not (cli_repo / ".github/workflows/python-checks.yml").exists()
    print("GitHub workflow installer: preview, required secret/permission, install, conflict and selected overwrite")


def check_ide_management() -> None:
    from atlas.api import workspace_router
    async def respond(method: str, params=None):
        if method == "status": return {"version": "0.1.0", "last_heartbeat": "2026-10-25T00:00:00Z", "workspace": "C:/fixture"}
        if method == "reconnect": return {"connected": True}
        if method == "configure": return {"opened": True}
        if method == "diagnostics": return [{"file": "sample.py", "severity": "warning", "message": "fixture", "startLine": 1, "endLine": 1}]
        raise AssertionError(method)
    async def scenario():
        with patch("atlas.tools.ide_bridge.request", side_effect=respond):
            status = await workspace_router.ide_status()
            assert status["connected"] and status["version"] == "0.1.0" and status["workspace"] == "C:/fixture"
            assert (await workspace_router.ide_reconnect())["connected"]
            assert (await workspace_router.ide_configure())["opened"]
            diagnostics = await workspace_router.ide_diagnostics()
            assert len(diagnostics["items"]) == 1
    asyncio.run(scenario())
    print("IDE management: live-status route, reconnect, configure and diagnostics bridge calls")


def check_video_attachment(base: Path) -> None:
    source = (ROOT / "frontend/src/renderer/components/ScreenRecorderDialog.tsx").read_text(encoding="utf-8")
    assert "getDisplayMedia" in source and "MAX_FRAME_RATE = 15" in source
    assert "MAX_DURATION_SECONDS = 300" in source and "MAX_RECORDING_BYTES = 10 * 1024 * 1024" in source
    assert "saveScreenRecording" in source and "deleteScreenRecording" in source and "作为附件发送给 Agent" in source
    from atlas.api import run_drive
    fake_home = base / "attachment-home"
    with patch("pathlib.Path.home", return_value=fake_home):
        payload = __import__("base64").b64encode(b"U20 test WebM payload").decode("ascii")
        text, paths = run_drive._validated_file_attachments(
            [{"name": "screen.webm", "mime": "video/webm", "data_base64": payload}], "u20-video", "Review this recording"
        )
        assert "Review this recording" == text and len(paths) == 1
        saved = Path(paths[0]); assert saved.read_bytes() == b"U20 test WebM payload"
    print("screen recording: capture limits, attachment ingestion, local storage path and deletion controls wired")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u20-") as tmp:
        base = Path(tmp)
        check_repository_review(base)
        check_github_workflow(base)
        check_ide_management()
        check_video_attachment(base)
    print("U20 CHECK PASS")


if __name__ == "__main__":
    main()
