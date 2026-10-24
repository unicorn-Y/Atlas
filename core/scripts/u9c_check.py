"""U9c regression check: PR workflow, diagnostics state, verified releases, project knowledge."""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core"))


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", check=True)
    return result.stdout.strip()


def check_pr_workflow(temp: Path) -> None:
    from fastapi import HTTPException
    import atlas.api.workspace_router as router

    repo, bare = temp / "repo", temp / "remote.git"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "check@example.invalid")
    git(repo, "config", "user.name", "U9c Check")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    git(repo, "add", "README.md"); git(repo, "commit", "-m", "initial")
    git(temp, "init", "--bare", str(bare))
    git(repo, "remote", "add", "origin", str(bare)); git(repo, "push", "-u", "origin", "main")
    git(repo, "remote", "set-head", "origin", "main")
    (repo / "feature.txt").write_text("feature\n", encoding="utf-8")
    real_run = subprocess.run
    gh_calls: list[list[str]] = []

    def fake_run(args, *rest, **kwargs):
        if args and args[0] == "gh":
            gh_calls.append(list(args))
            return subprocess.CompletedProcess(args, 0, "created\n", "")
        return real_run(args, *rest, **kwargs)

    pr = {"number": 9, "title": "Feature", "url": "https://example.invalid/pr/9", "state": "OPEN",
          "isDraft": False, "baseRefName": "main", "headRefName": "atlas/test", "statusCheckRollup": [],
          "autoMergeRequest": {"mergeMethod": "SQUASH"}}
    async def run():
        with patch.object(router, "_git_workspace", return_value=repo), \
             patch.object(router, "_gh_json", side_effect=[HTTPException(502, "no pull requests found"), pr]), \
             patch.object(router.subprocess, "run", side_effect=fake_run):
            result = await router.run_git_pr_wizard(SimpleNamespace(), {
                "root": str(repo), "paths": ["feature.txt"], "message": "feat: add feature",
                "title": "Feature", "body": "Adds feature", "branch": "atlas/test",
            })
            assert result["pr"]["number"] == 9 and result["branch"] == "atlas/test"
            with patch.object(router, "_gh_json", return_value={"autoMergeRequest": {"mergeMethod": "REBASE"}}):
                merged = await router.set_git_pr_auto_merge(SimpleNamespace(), {"root": str(repo), "enabled": True, "method": "rebase"})
                assert merged["enabled"]
    asyncio.run(run())
    assert any(call[:4] == ["gh", "pr", "create", "--title"] for call in gh_calls)
    assert any(call[:4] == ["gh", "pr", "merge", "--auto"] and "--rebase" in call for call in gh_calls)
    assert git(repo, "status", "--porcelain") == ""
    assert git(repo, "rev-parse", "HEAD") in git(bare, "rev-list", "--all")


def check_release_verification(temp: Path) -> None:
    payload = b"atlas installer fixture"
    checksum = hashlib.sha256(payload).hexdigest()
    bad_hash = False

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/latest"):
                body = {"tag_name": "v9.2.0", "body": "release notes", "assets": [
                    {"name": "Atlas-9.2.0-Setup.exe", "browser_download_url": self.server.base + "/installer"},
                    {"name": "Atlas-9.2.0-Setup.exe.sha256", "browser_download_url": self.server.base + "/checksum"},
                ]}
                data = json.dumps(body).encode()
            elif self.path.endswith("/installer"):
                data = payload
            elif self.path.endswith("/checksum"):
                data = (("0" * 64) if bad_hash else checksum).encode()
            else:
                self.send_error(404); return
            self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.base = f"http://127.0.0.1:{server.server_port}"  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    helper = ROOT / "frontend" / "src" / "main" / "releaseUpdate.ts"
    script = f"""
      Object.defineProperty(process, 'platform', {{ value: 'linux' }});
      const mod = await import({json.dumps(helper.as_uri())});
      const source = {json.dumps(server.base + '/latest')};
      if (mod.compareSemver('v9.2.0','9.1.9') <= 0) throw new Error('semver comparison failed');
      const status = await mod.checkReleaseUpdate(source, '9.1.0', {json.dumps(str(temp / 'user-data'))});
      if (!status.available || status.latest !== 'v9.2.0') throw new Error('release check failed');
      const file = await mod.downloadVerifiedInstaller(source, '9.2.0', {json.dumps(str(temp / 'user-data'))}, () => {{}});
      if (!file.endsWith('Atlas-9.2.0-Setup.exe')) throw new Error('installer was not saved');
      console.log('RELEASE_OK');
    """
    try:
        result = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", script],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if result.returncode or "RELEASE_OK" not in result.stdout:
            raise AssertionError(f"correct-hash local release failed: {result.stderr or result.stdout}")
        bad_hash = True
        bad_script = f"""
          Object.defineProperty(process, 'platform', {{ value: 'linux' }});
          const mod = await import({json.dumps(helper.as_uri())});
          try {{ await mod.downloadVerifiedInstaller({json.dumps(server.base + '/latest')}, '9.2.0', {json.dumps(str(temp / 'bad-user-data'))}, () => {{}}); }}
          catch (error) {{ if (String(error).includes('SHA256 不匹配')) {{ console.log('BAD_HASH_REJECTED'); process.exit(0); }} throw error; }}
          throw new Error('bad hash was accepted');
        """
        result = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", bad_script],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        assert result.returncode == 0 and "BAD_HASH_REJECTED" in result.stdout, result.stderr or result.stdout
    finally:
        server.shutdown(); thread.join(timeout=5)


async def check_project_knowledge(temp: Path) -> None:
    from atlas.projects import ProjectStore
    import atlas.api.projects_router as router
    import atlas.diagnostic_alerts as alerts

    workspace = temp / "workspace"
    (workspace / ".atlas").mkdir(parents=True)
    (workspace / ".atlas" / "NOTES.md").write_text("test-command: pytest\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("test-command: npm test\n", encoding="utf-8")
    store = ProjectStore(temp / "projects.db")
    await store.init()
    project = await store.create_project("U9c", str(workspace))
    with patch.object(router, "_server", return_value=SimpleNamespace(_workspace_path=lambda _root: (workspace, None))), \
         patch.object(router, "load_user_settings", return_value={"project_context_token_budget": 256}), \
         patch.object(alerts, "_PATH", temp / "alerts.json"):
        status = await router.get_project_context_status(SimpleNamespace(projects=store), project.project_id, str(workspace))
        assert any(item["key"] == "test-command" and len(item["claims"]) == 2 for item in status["conflicts"])
        assert status["budget"] == 256
        invalid = workspace / "bad-encoding.md"; invalid.write_bytes(b"\xff\xfe\x00")
        await store.add_source(project.project_id, "file", path=str(invalid))
        status = await router.get_project_context_status(SimpleNamespace(projects=store), project.project_id, str(workspace))
        assert any("bad-encoding.md" in row["file"] for row in status["errors"])
    await store.close()


def check_alert_persistence(temp: Path) -> None:
    import atlas.diagnostic_alerts as alerts
    with patch.object(alerts, "_PATH", temp / "alerts.json"):
        first = alerts.record_alert("startup", "Test warning", "persisted detail", dedupe_key="test")
        second = alerts.record_alert("startup", "Test warning", "persisted detail", dedupe_key="test")
        assert first["id"] == second["id"] and len(alerts._read()) == 1


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u9c-") as raw:
        temp = Path(raw)
        (temp / "git").mkdir()
        check_pr_workflow(temp / "git")
        check_alert_persistence(temp)
        check_release_verification(temp)
        asyncio.run(check_project_knowledge(temp))
    print("PR workflow, auto-merge, alert persistence, release hashes, project conflicts/budget/index errors: PASS")
    print("U9C CHECK PASS")


if __name__ == "__main__":
    main()
