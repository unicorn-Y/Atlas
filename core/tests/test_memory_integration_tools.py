from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from atlas.agent import AgentOrchestrator
from atlas.kernel.loop import AtlasKernel
from atlas.kernel.tools import READ_ONLY_TOOLS, kernel_tool_schemas
from atlas.evolution.skill_candidate import heldout_composition, score_candidate
from atlas.evolution.skill_staging import promote_candidate
from atlas.memory.library import MemoryLibrary
from atlas.memory.library.store import ME


def test_memory_open_is_registered_as_read_only_tool():
    schemas = kernel_tool_schemas(include_workflow=False)
    memory_open = next(
        item["function"] for item in schemas if item["function"]["name"] == "memory_open"
    )
    assert memory_open["parameters"]["required"] == ["ref"]
    assert "memory_open" in READ_ONLY_TOOLS


def test_skill_gates_fail_closed_without_heldout_or_blocker_evidence(tmp_path):
    report = SimpleNamespace(
        accepted=True, n_tasks=2, baseline_score=0.4, candidate_score=0.5,
    )
    assert not heldout_composition(report, {"ok"}, {"failed"})["passed"]
    assert not score_candidate(report, gate_mode="on")["passed"]

    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: demo\ndescription: demo\nversion: 0.0.0\n---\nbody\n", encoding="utf-8")
    assert promote_candidate(path, user_reviewed=True)["reason"] in {
        "stored_validation_gate_not_passed",
        "stored_promotion_evidence_incomplete_or_not_passed",
    }


def test_skill_gates_require_balanced_heldout_and_explicit_zero_blockers():
    report = SimpleNamespace(
        accepted=True, n_tasks=2, baseline_score=0.4, candidate_score=0.5,
        heldout_ids=["ok", "failed"], safety_blockers=0, correctness_blockers=0,
    )
    assert heldout_composition(report, {"ok"}, {"failed"})["passed"]
    assert score_candidate(report, gate_mode="on")["passed"]


def test_skill_promotion_auto_promotes_without_manual_review(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text("---\nname: demo\ndescription: demo\nversion: 0.0.0\n---\nbody\n", encoding="utf-8")
    result = promote_candidate(path)
    assert not result["promoted"]
    assert result["reason"] == "stored_promotion_evidence_incomplete_or_not_passed"


def test_forget_removes_linked_candidate_and_external_learned_skill(tmp_path, monkeypatch):
    from atlas import skills
    from atlas.evolution import skill_staging

    library = MemoryLibrary(tmp_path / "memory")
    library.ready()
    added = library.add_entry(ME, "derived skill source to forget")
    page, entry, _ = library.store.find_entry(added["id"])
    source_ref = {"conversation_id": "child-1", "message_uid": "uid-9"}
    entry.source_ref = source_ref
    library.store.write(page)

    skill_root = tmp_path / "skills"
    monkeypatch.setattr(skill_staging, "SKILLS_DIR", skill_root)
    monkeypatch.setattr(skills, "SKILLS_DIR", skill_root)
    candidate = tmp_path / "memory" / "技能候选" / "linked" / "SKILL.md"
    candidate.parent.mkdir(parents=True)
    candidate.write_text(
        "---\nname: linked\ndescription: linked\nversion: 0.0.0\n"
        "metadata:\n  source_refs:\n    - conversation_id: child-1\n      message_uid: uid-9\n---\nsteps\n",
        encoding="utf-8",
    )
    live = skill_root / "learned" / "linked" / "SKILL.md"
    live.parent.mkdir(parents=True)
    live.write_text("learned from this source", encoding="utf-8")
    library.store.commit("stage linked learned skill")

    result = library.forget_entry(added["id"])

    assert not candidate.exists()
    assert not live.exists()
    assert result["skills_removed"] == ["linked"]
    assert "技能候选/linked/SKILL.md" in result["history"]["removed"]


@pytest.mark.asyncio
async def test_memory_open_dispatches_exact_ref(monkeypatch):
    from atlas.memory import library
    from atlas.memory.library import sources

    monkeypatch.setattr(library, "get_library", lambda: object())
    opened = []

    def open_ref(ref, window):
        opened.append((ref, window))
        return {"ref": ref, "text": "bounded source"}

    monkeypatch.setattr(sources, "open_ref", open_ref)
    result = await AtlasKernel._dispatch(
        object.__new__(AtlasKernel), None, SimpleNamespace(conversation_id="parent"),
        "call-1", "memory_open", {"ref": "atlas://source/v1?id=exact"},
        asyncio.Queue(),
    )
    assert opened == [("atlas://source/v1?id=exact", 1)]
    assert result["data"]["text"] == "bounded source"


@pytest.mark.asyncio
async def test_atlas_child_session_can_be_retained_for_exact_source(tmp_path, monkeypatch):
    deleted_sessions = []
    monkeypatch.setattr("atlas.config.DATA_ROOT", tmp_path)
    monkeypatch.setattr(
        "atlas.engine.session_sync.delete_session",
        lambda root, conversation_id: deleted_sessions.append(conversation_id),
    )

    class Memory:
        def __init__(self):
            self.deleted = []

        async def create_conversation(self, _title):
            return "child-retained"

        async def delete_conversation(self, conversation_id):
            self.deleted.append(conversation_id)

    async def fake_run(*_args, **_kwargs):
        yield {"type": "chunk", "content": "child result"}

    agent = object.__new__(AgentOrchestrator)
    memory = Memory()
    monkeypatch.setattr(agent, "_memory", memory, raising=False)
    monkeypatch.setattr(agent, "run", fake_run)
    result = await agent._run_atlas_subtask(
        goal="retain source", context=None, cwd=None, subtask_id="retain-child",
        atlas_options={"retain_child_session": True}, on_progress=lambda _text: None,
    )
    assert result["session_id"] == "child-retained"
    assert deleted_sessions == []
    assert memory.deleted == []
