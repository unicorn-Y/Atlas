from __future__ import annotations

import json

from atlas.evolution import watcher
from atlas.evolution.run_learning import record_terminal_run, transcript_excerpt
from atlas.evolution.skill_curator import SkillCurator


def test_terminal_outcomes_auto_create_only_success_candidates(tmp_path, monkeypatch):
    root = tmp_path / "evolution"
    monkeypatch.setattr(watcher, "evolution_root", lambda: root)

    failed = record_terminal_run(
        run_id="failed-1", conversation_id="conv-1", status="failed",
        user_text="secret prompt", assistant_text="secret response",
    )
    assert failed["candidate"] is None
    failed_signal = json.loads((root / "run-outcomes" / "failed-1.json").read_text("utf-8"))
    assert failed_signal["status"] == "failed"
    assert "secret" not in json.dumps(failed_signal)

    completed = record_terminal_run(
        run_id="complete-1", conversation_id="conv-1", status="completed",
        project_id="project-1", agent_id="agent-1",
        user_text="整理本周提交", assistant_text="1. 汇总提交\n2. 输出摘要",
    )
    candidate = completed["candidate"]
    assert candidate["status"] == "candidate"
    assert candidate["origin"] == "successful_run"
    assert candidate["source_runs"] == ["complete-1"]
    assert candidate["parameters"]["project_id"] == "project-1"
    assert candidate["parameters"]["agent_id"] == "agent-1"
    assert "整理本周提交" in candidate["parameters"]["steps"][0]

    duplicate = record_terminal_run(
        run_id="complete-1", conversation_id="conv-1", status="completed",
        user_text="整理本周提交", assistant_text="1. 汇总提交\n2. 输出摘要",
    )
    assert duplicate["duplicate"] is True
    assert duplicate["candidate"]["id"] == candidate["id"]
    assert len(SkillCurator().list()) == 1


def test_conversation_extraction_is_scoped_to_source_run():
    messages = [
        {"role": "user", "content": "旧任务", "metadata": {"run_id": "old"}},
        {"role": "assistant", "content": "旧结果", "metadata": {"run_id": "old"}},
        {"role": "user", "content": "新任务", "metadata": {"run_id": "new"}},
        {"role": "assistant", "content": "新结果", "metadata": {"run_id": "new"}},
    ]
    assert transcript_excerpt(messages, "new") == ("新任务", "新结果")


def test_candidate_text_force_redacts_credential_values(tmp_path):
    secret = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"
    candidate = SkillCurator(tmp_path / "candidates").create_candidate_from_conversation(
        conversation_id="conversation-2", run_id="run-2",
        user_text=f"deploy with token {secret}", assistant_text=f"saved token {secret}",
    )
    assert secret not in json.dumps(candidate, ensure_ascii=False)


def test_candidate_approval_can_be_rolled_back_with_provenance(tmp_path):
    curator = SkillCurator(tmp_path / "candidates")
    record = curator.create_candidate_from_conversation(
        conversation_id="conversation-1", run_id="run-1",
        user_text="生成周报", assistant_text="汇总提交并输出周报",
    )
    curator.approve(record["id"])
    rolled_back = curator.mark_rolled_back(record["id"])
    assert rolled_back["status"] == "rolled_back"
    assert rolled_back["source_runs"] == ["run-1"]
    assert rolled_back["provenance"]["history"][-1]["action"] == "rolled_back"


async def test_terminal_event_capture_and_project_skill_scope(tmp_path, monkeypatch):
    root = tmp_path / "evolution"
    monkeypatch.setattr(watcher, "evolution_root", lambda: root)
    from atlas.api import run_drive
    from atlas.api.runtime import RunState, RuntimeManager
    from atlas import project_settings

    async def messages(_conversation_id, limit=1000):
        assert limit == 500
        return [
            {"role": "user", "content": "生成版本摘要", "metadata": {"run_id": "success-1"}},
            {"role": "assistant", "content": "整理标签并输出 Markdown", "metadata": {"run_id": "success-1"}},
        ]

    monkeypatch.setattr(run_drive, "_session_messages", messages)
    completed = RunState("success-1", "conversation-1", "test")
    completed.user_input = "生成版本摘要"
    completed.project_id = "project-1"
    completed.agent_id = "agent-1"
    await run_drive._capture_evolution_outcome(completed, "run.completed")
    assert (root / "run-outcomes" / "success-1.json").exists()
    assert SkillCurator().get("run-success-1")["source_runs"] == ["success-1"]

    failed = RunState("failed-1", "conversation-1", "test")
    await run_drive._capture_evolution_outcome(failed, "run.failed")
    assert (root / "run-outcomes" / "failed-1.json").exists()
    assert SkillCurator().get("run-failed-1") is None

    monkeypatch.setattr(project_settings, "load_project_config", lambda _id: {
        "active_skills": ["release-notes", "repo-map", "release-notes"],
    })

    class Projects:
        async def find_by_conversation(self, conversation_id):
            assert conversation_id == "conversation-1"
            return type("Project", (), {"project_id": "project-1"})()

    manager = RuntimeManager()
    manager.runs["success-1"] = completed
    scope, skills = await run_drive._resolve_project_skill_scope(
        {"conversation_id": "conversation-1"}, manager, Projects(),
        ignore_project_config=False,
    )
    assert scope == "project-1" and skills == ["release-notes", "repo-map"]
    assert await run_drive._resolve_project_skill_scope(
        {"project_id": "project-1"}, manager, Projects(), ignore_project_config=True,
    ) == ("project-1", [])
