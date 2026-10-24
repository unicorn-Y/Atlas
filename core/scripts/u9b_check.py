"""Focused persistence, namespace, desktop-recipe, and secret-injection checks."""
from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from pathlib import Path

from atlas import computer_teach, secrets_store
from atlas.projects import ProjectStore

def check_routes() -> None:
    from atlas.api.computer_router import router as computer_router
    from atlas.api.projects_router import router as projects_router
    from atlas.api.secrets_router import router as secrets_router
    computer_paths = {route.path for route in computer_router.routes}
    project_paths = {route.path for route in projects_router.routes}
    secret_paths = {route.path for route in secrets_router.routes}
    assert {"/api/computer/teach/start", "/api/computer/teach/stop", "/api/computer/teach/replay", "/api/computer/teach/export"} <= computer_paths
    assert {"/api/secrets", "/api/secrets/{name}/reveal"} <= secret_paths
    assert "/api/projects/{project_id}/memories" in project_paths


async def check_projects(root: Path) -> None:
    store = ProjectStore(root / "projects.sqlite")
    await store.init()
    a = await store.create_project("A")
    b = await store.create_project("B")
    await store.add_project_memory(a.project_id, "PROJECT_A_SENTINEL migration requires careful tests")
    await store.add_project_memory(b.project_id, "PROJECT_B_SENTINEL")
    await store.add_project_memory(a.project_id, "TO_DELETE")
    await store.add_project_memory(a.project_id, "TO_GLOBAL")
    await store.add_project_memory(a.project_id, "TO_ARCHIVE")
    assert not await store.search_project_memories(b.project_id, "PROJECT_A_SENTINEL")
    assert len(await store.search_project_memories(a.project_id, "PROJECT_A_SENTINEL")) == 1
    await store.add_project_memory(a.project_id, "ONLY_PROJECT_MEMORY")
    global_rows = await store.search_global_memories("GLOBAL_ONLY_SENTINEL")
    assert not global_rows
    await store.add_project_memory(a.project_id, "GLOBAL_ONLY_SENTINEL")
    global_source = (await store.search_project_memories(a.project_id, "GLOBAL_ONLY_SENTINEL"))[0]
    await store.move_project_memory(global_source["id"], None)
    assert len(await store.search_global_memories("GLOBAL_ONLY_SENTINEL")) == 1
    assert not await store.recall_project_memories(a.project_id, "GLOBAL_ONLY_SENTINEL", project_only=True)
    assert await store.recall_project_memories(a.project_id, "GLOBAL_ONLY_SENTINEL", project_only=False)
    assert not await store.recall_project_memories(b.project_id, "PROJECT_A_SENTINEL", project_only=True)
    await store.delete_project(a.project_id, "delete")
    assert not await store.search_project_memories(a.project_id, "TO_DELETE")
    await store.delete_project(b.project_id, "archive")
    assert len(await store.search_project_memories("archived:" + b.project_id, "PROJECT_B_SENTINEL")) == 1
    c = await store.create_project("C")
    await store.add_project_memory(c.project_id, "MOVE_TO_GLOBAL_SENTINEL")
    await store.delete_project(c.project_id, "global")
    assert len(await store.search_global_memories("MOVE_TO_GLOBAL_SENTINEL")) == 1
    await store.close()


async def check_secrets(root: Path) -> None:
    secrets_store._META = root / "secrets.json"
    secrets_store._BLOB = root / "secrets.enc"
    secrets_store._KEY = root / "secrets.key"
    secrets_store._keyring = lambda: None
    secret = "u9b_sensitive_value_7391"
    secrets_store.set_secret("U9B_TEST_TOKEN", secret, "temporary check")
    assert secrets_store.list_secrets()[0]["backend"] == "encrypted-file"
    environment = secrets_store.resolve_env({"TOKEN": "{{secret:U9B_TEST_TOKEN}}"})
    child = subprocess.run([os.sys.executable, "-c", "import os; print(os.environ['TOKEN'])"], env={**os.environ, **environment}, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    assert child.stdout.strip() == secret
    from atlas.tools.local_execution import LocalExecutionRuntime
    runtime = LocalExecutionRuntime(); runtime.permission_mode = "full_access"
    result = await runtime.call_tool("local_exec", {"executable": os.sys.executable, "args": ["-c", "import os; print(os.environ['TOKEN'])"], "cwd": str(root), "env": {"TOKEN": "{{secret:U9B_TEST_TOKEN}}"}})
    rendered = str(result)
    assert secret not in rendered
    record = next(iter(runtime._processes.values()))
    persisted = record.stdout_path.read_text(encoding="utf-8", errors="replace")
    assert secret not in persisted, "secret appeared in the persisted process log"
    assert "{{secret:U9B_TEST_TOKEN}}" in persisted, f"process log did not contain the expected redacted output; chars={len(persisted)} result={secrets_store.redact(rendered)}"
    await runtime.shutdown()
    assert secrets_store.delete_secret("U9B_TEST_TOKEN")


async def check_teaching(root: Path) -> None:
    import atlas.skills
    atlas.skills.SKILLS_DIR = root / "skills"
    computer_teach._SESSION = {"id": "check", "recording": False, "count": 2, "steps": [
        {"id": "1", "action": "click", "x": 10, "y": 20, "window": {"title": "Demo", "process": "12"}, "anchor": "cGl4ZWxz"},
        {"id": "2", "action": "sensitive_input", "key": "[内容已脱敏]"},
    ], "started": 1.0, "stop_event": __import__("threading").Event()}
    edited = computer_teach.correct(computer_teach.snapshot()["steps"])
    assert edited["count"] == 2 and edited["steps"][1]["key"] == "[内容已脱敏]"
    exported = computer_teach.export_skill("u9b-check-skill", "测试技能", ["filename"])
    text = Path(exported["path"]).read_text(encoding="utf-8")
    assert "filename" in text and "锚点截图匹配" in text and "敏感" in text
    assert (Path(exported["path"]).parent / "anchors.json").exists()
    manager = atlas.skills.SkillManager(); manager.scan_skills_sync()
    assert any(item.name == "u9b-check-skill" for item in manager.list_skills())
    from types import SimpleNamespace
    from atlas.api.computer_router import teach_export
    class FakeModelRouter:
        async def complete_for(self, model: str, purpose: str, messages: list[dict[str,str]], **kwargs):
            assert model == "test-model" and purpose == "conversation"
            assert "内容已脱敏" in messages[1]["content"]
            return SimpleNamespace(text="---\nname: u9b-model-skill\ndescription: generated\n---\n\n## 参数\nfilename\n\n## 步骤\n1. window locator then screenshot anchor then coordinates")
    fake_manager=SimpleNamespace(current_model="test-model",model_router=FakeModelRouter())
    fake_services=SimpleNamespace(model_mgr=fake_manager,skill_mgr=manager)
    fake_request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=fake_services)))
    result=await teach_export({"name":"u9b-model-skill","purpose":"test","parameters":["filename"]},fake_request)
    assert result["name"]=="u9b-model-skill"
    assert any(item.name=="u9b-model-skill" for item in manager.list_skills())


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u9b-") as folder:
        root = Path(folder)
        await check_secrets(root)
        await check_teaching(root)
        await check_projects(root)
        check_routes()
    print("U9b data-path checks passed")
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
