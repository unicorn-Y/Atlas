"""W7 Skill Proposal store tests — full lifecycle, stale conflict, ledger, rollback.

Storage is the SAME SQLite file as the Registry (single-store red line); these
tests use a tmp_path registry + market so nothing touches the operator home.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from atlas.skills.agent_collections import AgentSkillCollections
from atlas.skills.market import ORIGIN_KINDS, SkillMarket
from atlas.skills.proposals import (
    EMPTY_REVISION,
    ProposalConflict,
    ProposalError,
    ProposalNotFound,
    ProposalStale,
    SkillProposalStore,
    files_revision,
)
from atlas.skills.registry import SkillRegistry


def skill_md(name: str, version: str, description: str = "Learned skill") -> str:
    return (
        "---\n"
        f"name: {name}\n"
        f"version: {version}\n"
        f"description: {description}\n"
        "---\n"
        f"# {name}\n\nBody for {name} v{version}.\n"
    )


class Env:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp = tmp_path
        self.registry = SkillRegistry(tmp_path / "atlas.db")
        self.user_skills = tmp_path / "skills"
        self.market = SkillMarket(
            self.registry, data_dir=tmp_path / "data", user_skills_dir=self.user_skills,
        )
        self.collections = AgentSkillCollections(self.registry)
        self.store = SkillProposalStore(
            self.registry, market=self.market, collections=self.collections,
        )

    def seed_skill(self, name: str, version: str = "1.0.0") -> Path:
        """Install an agent-learned base skill straight through the market API."""
        skill_dir = self.user_skills / "community" / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(skill_md(name, version), encoding="utf-8")
        (skill_dir / "README.md").write_text("notes\n", encoding="utf-8")
        self.market.register_local(
            name, path=skill_dir, origin_kind="agent_learned",
            source="agent", reason="seed")
        return skill_dir


@pytest.fixture()
def env(tmp_path):
    return Env(tmp_path)


# ---------------------------------------------------------------------------
# ORIGIN_KINDS whitelist (the one allowed market.py change)
# ---------------------------------------------------------------------------

def test_origin_kinds_contains_agent_learned() -> None:
    assert "agent_learned" in ORIGIN_KINDS
    assert "local_recorded" in ORIGIN_KINDS and "local_evolved" in ORIGIN_KINDS


def test_register_local_accepts_agent_learned(env) -> None:
    env.seed_skill("seeded-skill")
    record = [r for r in env.registry.list() if r["name"] == "seeded-skill"][0]
    provenance = record["provenance"]
    assert provenance["origin_kind"] == "agent_learned"
    assert record["status"] == "active"


# ---------------------------------------------------------------------------
# Lifecycle: create -> approve -> applied -> registry truth -> rollback
# ---------------------------------------------------------------------------

def test_create_approve_applied_registry_effective_and_rollback(env) -> None:
    origin = {"agent_id": "agent-1", "session_key": "agent:agent-1:kind:peer",
              "run_id": "run-7", "message_id": "msg-3"}
    record = env.store.create_proposal(
        "newly-learned",
        files={"SKILL.md": skill_md("newly-learned", "1.0.0"),
               "references.md": "ref\n"},
        origin=origin, goal="agent kept repeating a fix-up flow",
        evidence="3 successful runs", created_by="agent",
    )
    assert record["status"] == "pending"
    assert record["kind"] == "create"
    assert record["source_kind"] == "agent_learned"
    assert record["base_revision"] == EMPTY_REVISION
    assert record["proposed_diff"]["writes"]["SKILL.md"].startswith("---")
    assert env.registry.list() == []  # nothing applied yet

    approved = env.store.approve(record["proposal_id"], reviewer_note="looks safe")
    assert approved["status"] == "applied"
    assert approved["decided_at"]
    assert approved["applied"]["version"] == "1.0.0"

    # Registry really has the skill now (single store), payload written on disk.
    rows = [r for r in env.registry.list() if r["name"] == "newly-learned"]
    assert [r["version"] for r in rows] == ["1.0.0"]
    assert rows[0]["status"] == "active"
    assert rows[0]["provenance"]["origin_kind"] == "agent_learned"
    dest = env.user_skills / "community" / "newly-learned"
    assert (dest / "SKILL.md").is_file() and (dest / "references.md").is_file()

    # learned relation default-enabled for the origin agent (entity not copied).
    relation = env.collections.get_agent_skill("agent-1", "newly-learned")
    assert relation["relation"] == "learned" and relation["enabled"] is True

    # Event ledger: created -> applied, in order.
    events = env.store.events(record["proposal_id"])
    assert [e["event"] for e in events] == ["created", "applied"]
    assert events[1]["payload"]["version"] == "1.0.0"

    # Rollback restores absence (create): registry rows gone, directory gone.
    rolled = env.store.rollback(record["proposal_id"])
    assert rolled["rolled_back_at"]
    assert not [r for r in env.registry.list() if r["name"] == "newly-learned"]
    assert not dest.exists()
    events = env.store.events(record["proposal_id"])
    assert [e["event"] for e in events] == ["created", "applied", "rolled_back"]
    with pytest.raises(ProposalConflict):
        env.store.rollback(record["proposal_id"])  # second rollback refused


def test_update_lifecycle_rollback_restores_previous_payload(env) -> None:
    env.seed_skill("patchable-skill")
    record = env.store.create_proposal(
        "patchable-skill",
        files={"SKILL.md": skill_md("patchable-skill", "1.0.1")},
        deletes=["README.md"],
        origin={"agent_id": "agent-1"},
    )
    assert record["kind"] == "update"
    base_hash = files_revision({
        "SKILL.md": skill_md("patchable-skill", "1.0.0"), "README.md": "notes\n",
    })
    assert record["base_revision"] == base_hash

    env.store.approve(record["proposal_id"])
    versions = sorted(
        r["version"] for r in env.registry.list() if r["name"] == "patchable-skill")
    assert versions == ["1.0.1"]  # managed 1.0.0 row dropped by the apply
    dest = env.user_skills / "community" / "patchable-skill"
    assert not (dest / "README.md").exists()

    rolled = env.store.rollback(record["proposal_id"])
    assert rolled["restored"]["version"] == "1.0.0"
    versions = sorted(
        r["version"] for r in env.registry.list() if r["name"] == "patchable-skill")
    assert versions == ["1.0.0"]
    assert env.registry.get("patchable-skill", "1.0.0")["status"] == "active"
    assert (dest / "README.md").is_file()  # deleted file is back


# ---------------------------------------------------------------------------
# Stale / conflict semantics
# ---------------------------------------------------------------------------

def test_stale_conflict_when_base_revision_expired(env) -> None:
    env.seed_skill("drifting-skill")
    record = env.store.create_proposal(
        "drifting-skill",
        files={"SKILL.md": skill_md("drifting-skill", "1.0.1")},
    )
    # Base drifts underneath the draft: a new version lands in the registry.
    env.seed_skill("drifting-skill", version="1.1.0")

    with pytest.raises(ProposalStale):
        env.store.approve(record["proposal_id"])
    stale = env.store.get(record["proposal_id"])
    assert stale["status"] == "stale" and stale["decided_at"]
    assert [e["event"] for e in env.store.events(record["proposal_id"])][-1] == "stale"
    # A drifted proposal never touched the registry.
    assert sorted(
        r["version"] for r in env.registry.list() if r["name"] == "drifting-skill"
    ) == ["1.0.0", "1.1.0"]
    # Stale proposals can still be rejected (reviewer closes them out).
    rejected = env.store.reject(record["proposal_id"], reason="obsolete")
    assert rejected["status"] == "rejected"


def test_expected_revision_optimistic_lock(env) -> None:
    record = env.store.create_proposal(
        "locked-skill", files={"SKILL.md": skill_md("locked-skill", "1.0.0")})
    old_hash = record["revision_hash"]
    revised = env.store.revise_proposal(
        record["proposal_id"],
        files={"SKILL.md": skill_md("locked-skill", "1.0.0"),
               "notes.md": "v2 draft\n"})
    assert revised["revision_hash"] != old_hash
    with pytest.raises(ProposalConflict) as excinfo:
        env.store.approve(record["proposal_id"], expected_revision=old_hash)
    assert excinfo.value.code == "revision_conflict"
    assert env.store.get(record["proposal_id"])["status"] == "pending"
    # Correct hash approves fine.
    approved = env.store.approve(record["proposal_id"], expected_revision=revised["revision_hash"])
    assert approved["status"] == "applied"


def test_state_machine_guards(env) -> None:
    record = env.store.create_proposal(
        "guarded-skill", files={"SKILL.md": skill_md("guarded-skill", "1.0.0")})
    marked = env.store.mark_stale(record["proposal_id"], reason="manual sweep")
    assert marked["status"] == "stale"
    with pytest.raises(ProposalConflict):
        env.store.approve(record["proposal_id"])
    with pytest.raises(ProposalConflict):
        env.store.mark_stale(record["proposal_id"])
    with pytest.raises(ProposalConflict):
        env.store.rollback(record["proposal_id"])
    with pytest.raises(ProposalNotFound):
        env.store.approve("prop-missing")


def test_kind_mismatch_rejected(env) -> None:
    env.seed_skill("existing-skill")
    with pytest.raises(ProposalError):
        env.store.create_proposal(
            "existing-skill", kind="create",
            files={"SKILL.md": skill_md("existing-skill", "2.0.0")})
    with pytest.raises(ProposalError):
        env.store.create_proposal(
            "missing-skill", kind="update",
            files={"SKILL.md": skill_md("missing-skill", "1.0.0")})


# ---------------------------------------------------------------------------
# /learn semantics + ledger integrity
# ---------------------------------------------------------------------------

def test_same_name_pending_draft_is_revised_not_duplicated(env) -> None:
    first = env.store.create_proposal(
        "learn-once", files={"SKILL.md": skill_md("learn-once", "1.0.0")},
        origin={"agent_id": "agent-1", "run_id": "run-1"})
    second = env.store.create_proposal(
        "learn-once", files={"SKILL.md": skill_md("learn-once", "1.0.0"),
                             "steps.md": "1. do it\n"},
        origin={"agent_id": "agent-1", "run_id": "run-2"})
    assert second["proposal_id"] == first["proposal_id"]
    assert second["proposed_diff"]["writes"].get("steps.md") == "1. do it\n"
    events = env.store.events(first["proposal_id"])
    assert [e["event"] for e in events] == ["created", "revised"]
    # origin of the latest draft run is visible in the created event payload;
    # the revise event records the superseding note.
    assert events[1]["payload"]["revision_hash"] == second["revision_hash"]


def test_event_ledger_is_append_only(env) -> None:
    record = env.store.create_proposal(
        "ledger-skill", files={"SKILL.md": skill_md("ledger-skill", "1.0.0")})
    env.store.reject(record["proposal_id"], reason="no")
    with sqlite3.connect(env.registry.path) as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE skill_proposal_events SET event='applied' WHERE event='created'")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("DELETE FROM skill_proposal_events")
    events = env.store.events(record["proposal_id"])
    assert [e["event"] for e in events] == ["created", "rejected"]
    assert events[0]["sequence"] < events[1]["sequence"]
    assert events[1]["payload"]["reason"] == "no"


def test_proposal_listing_filters(env) -> None:
    a = env.store.create_proposal(
        "filter-a", files={"SKILL.md": skill_md("filter-a", "1.0.0")})
    env.store.create_proposal(
        "filter-b", files={"SKILL.md": skill_md("filter-b", "1.0.0")})
    env.store.reject(a["proposal_id"])
    pending = env.store.list(status="pending")
    assert [p["skill_name"] for p in pending] == ["filter-b"]
    rejected = env.store.list(status="rejected")
    assert [p["skill_name"] for p in rejected] == ["filter-a"]
    by_skill = env.store.list(skill_name="filter-a")
    assert len(by_skill) == 1 and by_skill[0]["status"] == "rejected"


def test_tables_share_the_registry_database_file(env) -> None:
    with sqlite3.connect(env.registry.path) as db:
        names = {
            row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert {
        "skill_registry", "skill_proposals", "skill_proposal_events",
        "skill_proposal_rollbacks", "agent_skills", "skill_usage",
    } <= names
