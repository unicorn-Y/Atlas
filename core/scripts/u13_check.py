from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import patch

from atlas.automation.engine import AutomationEngine
from atlas.engine_core.goal_command import dispatch_goal_command
from atlas.engine_core.goals import GoalManager
from atlas.rewind import RewindManager
from atlas.agent.checkpoints import ShadowGitCheckpointStore
from atlas.review.engine import build_child_goal, parse_scope
from atlas.kernel.tools import kernel_tool_schemas


def check_goal_resume() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u13-goal-") as temp:
        manager = GoalManager("u13", home=temp)
        manager.set("Deliver a multi-step change")
        assert not dispatch_goal_command(manager, "subgoal add Inspect requirements", authorize_gate=lambda: None).error
        assert not dispatch_goal_command(manager, "subgoal add Implement and verify", authorize_gate=lambda: None).error
        dispatch_goal_command(manager, "subgoal done 1", authorize_gate=lambda: None)
        resumed = GoalManager("u13", home=temp)
        assert resumed.state and resumed.state.completed_subgoals == [1]
        prompt = resumed.next_continuation_prompt()
        assert "Resume at the first incomplete subgoal: 2. Implement and verify" in prompt
        assert "[x] 1. Inspect requirements" in resumed.render_subgoals()
        schemas = {item["function"]["name"] for item in kernel_tool_schemas(include_workflow=False)}
        assert "goal_subgoal" in schemas
        assert "fn_name == \"goal_subgoal\"" in Path("core/atlas/agent/tool_node.py").read_text(encoding="utf-8")


def check_workspace_rewind() -> None:
    with tempfile.TemporaryDirectory(prefix="atlas-u13-rewind-") as temp:
        root = Path(temp) / "workspace"
        root.mkdir()
        file = root / "tracked.txt"
        file.write_text("before\n", encoding="utf-8")
        manager = RewindManager(ShadowGitCheckpointStore(Path(temp) / "snapshots"),
                                conversation_position=lambda _conversation: "prior-message",
                                truncate_conversation=lambda *_: None)
        point_id = manager.checkpoint_before_turn("conversation", "turn-1", root)
        file.write_text("after\n", encoding="utf-8")
        added = root / "new.txt"
        added.write_text("new\n", encoding="utf-8")
        preview = manager.preview(point_id)
        assert [(item.path, item.status) for item in preview.changes] == [
            ("new.txt", "added"), ("tracked.txt", "modified")]
        result = manager.rewind(point_id, "both")
        assert result.restored_files == ["new.txt", "tracked.txt"]
        assert file.read_text(encoding="utf-8") == "before\n" and not added.exists()


async def check_global_automation_pause() -> None:
    records = [
        {"id": "active", "name": "active", "enabled": True, "state": {}},
        {"id": "disabled", "name": "disabled", "enabled": False, "state": {}},
        {"id": "manual", "name": "manual", "enabled": True, "state": {"paused_reason": "user"}},
    ]
    class Store:
        def list(self): return [dict(r, state=dict(r["state"])) for r in records]
        def get(self, aid): return next((dict(r, state=dict(r["state"])) for r in records if r["id"] == aid), None)
    engine = AutomationEngine.__new__(AutomationEngine)
    engine._store = Store()
    engine._started = True
    engine._dbos = object()
    engine._wf = object()
    engine._emergency_lock = asyncio.Lock()
    async def pause(aid, reason="user"):
        next(r for r in records if r["id"] == aid)["state"]["paused_reason"] = reason
    async def resume(aid, **_kwargs):
        next(r for r in records if r["id"] == aid)["state"]["paused_reason"] = None
    async def cancel(aid): return {"cancelled": ["run-1"] if aid == "active" else []}
    engine.pause, engine.resume, engine.cancel = pause, resume, cancel
    with tempfile.TemporaryDirectory(prefix="atlas-u13-pause-") as temp, patch("atlas.config.DATA_ROOT", Path(temp)):
        paused = await engine.emergency_pause()
        assert paused["paused"] and paused["resume_ids"] == ["active"]
        assert next(r for r in records if r["id"] == "active")["state"]["paused_reason"] == "global-emergency"
        assert await engine.trigger_event("active") == {"fired": False, "reason": "global-emergency-pause"}
        try:
            await engine.run_now("active")
        except RuntimeError as exc:
            assert "全局紧急暂停" in str(exc)
        else:
            raise AssertionError("manual automation run escaped the emergency pause")
        resumed = await engine.emergency_resume()
        assert not resumed["paused"] and resumed["resumed"] == ["active"]
        assert next(r for r in records if r["id"] == "disabled")["enabled"] is False
        assert next(r for r in records if r["id"] == "manual")["state"]["paused_reason"] == "user"


def check_review_modes() -> None:
    security = parse_scope("/security-review branch feature-x")
    assert security == {"scope": "branch", "ref": "feature-x", "mode": "security", "user_prompt": ""}
    security_prompt = build_child_goal({**security, "scope_label": "分支 feature-x 相对 main"})
    assert "信任边界" in security_prompt and "攻击前提" in security_prompt
    cleanup = parse_scope("/simplify reduce duplicate parsing")
    cleanup_prompt = build_child_goal(cleanup)
    assert cleanup["mode"] == "cleanup-only" and "保持外部行为不变" in cleanup_prompt


def check_system_permission_contract() -> None:
    electron = Path("frontend/src/main/electron.ts").read_text(encoding="utf-8")
    ui = Path("frontend/src/renderer/components/x2/ComputerStatusSection.tsx").read_text(encoding="utf-8")
    assert "getSystemAccessStatus()" in electron and "platform:request-system-access" in electron
    assert "app:session-screenshot-error" in electron and "system settings" not in electron.lower()
    assert "屏幕录制" in electron and "打开辅助功能设置" in ui or "Privacy_Accessibility" in electron and "辅助功能" in ui
    assert "openSystemPrivacySettings" in ui and "重新检查授权" in ui
    assert "重新捕获截图" in ui and "platform:retry-session-screenshot" in electron


async def main() -> None:
    check_goal_resume()
    check_workspace_rewind()
    await check_global_automation_pause()
    check_review_modes()
    check_system_permission_contract()
    print("U13 CHECK PASS")


if __name__ == "__main__":
    asyncio.run(main())
