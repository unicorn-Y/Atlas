"""X18 residual: the per-scope-chain discovery cache for ``with_sources``.

The W4-Z6 seam builds a request-scoped SkillManager and rescanned the whole
filesystem on every call. The cache keys a view by its scope chain (base
ladder + request sources) and reuses the existing ``_ensure_fresh``
fingerprint contract for disk invalidation — no watcher, no new protocol.
"""

import os

import pytest

from atlas.skills import SkillManager, SkillSource

pytestmark = pytest.mark.unit


def _make_skill(root, relpath, name, description):
    path = root / relpath / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nBody of {name}",
        encoding="utf-8",
    )
    return path


def test_same_scope_chain_returns_the_cached_view(tmp_path):
    base_dir = tmp_path / "base"
    extra = tmp_path / "extra"
    _make_skill(base_dir, "tools/demo", "demo", "Base demo")
    _make_skill(extra, "review", "review", "Extra review")

    base = SkillManager(base_dir)
    chain = [SkillSource("request-scope", extra, 40, layout="flat")]

    first = base.with_sources(chain)
    second = base.with_sources(chain)

    assert first is second
    assert {skill.name for skill in first.list_skills()} == {"demo", "review"}


def test_different_scope_chain_gets_a_fresh_view(tmp_path):
    base_dir = tmp_path / "base"
    extra_a = tmp_path / "extra-a"
    extra_b = tmp_path / "extra-b"
    _make_skill(base_dir, "tools/demo", "demo", "Base demo")
    _make_skill(extra_a, "one", "one", "One")
    _make_skill(extra_b, "two", "two", "Two")

    base = SkillManager(base_dir)
    view_a = base.with_sources([SkillSource("scope-a", extra_a, 40, layout="flat")])
    view_b = base.with_sources([SkillSource("scope-b", extra_b, 40, layout="flat")])

    assert view_a is not view_b
    assert {skill.name for skill in view_a.list_skills()} == {"demo", "one"}
    assert {skill.name for skill in view_b.list_skills()} == {"demo", "two"}
    # The cache remembers both chains.
    assert base.with_sources([SkillSource("scope-a", extra_a, 40, layout="flat")]) is view_a


def test_base_source_registration_invalidates_cached_views(tmp_path):
    base_dir = tmp_path / "base"
    extra = tmp_path / "extra"
    late = tmp_path / "late"
    _make_skill(base_dir, "tools/demo", "demo", "Base demo")
    _make_skill(extra, "review", "review", "Extra review")
    _make_skill(late, "late-arrival", "late-arrival", "Registered later")

    base = SkillManager(base_dir)
    chain = [SkillSource("request-scope", extra, 40, layout="flat")]
    first = base.with_sources(chain)
    assert "late-arrival" not in {skill.name for skill in first.list_skills()}

    base.register_skill_source(SkillSource("claude-project", late, 30, layout="flat"))
    second = base.with_sources(chain)

    assert second is not first
    assert "late-arrival" in {skill.name for skill in second.list_skills()}
    assert "review" in {skill.name for skill in second.list_skills()}


def test_cached_view_stays_fresh_across_disk_edits(tmp_path):
    base_dir = tmp_path / "base"
    extra = tmp_path / "extra"
    _make_skill(base_dir, "tools/demo", "demo", "Base demo")
    review = _make_skill(extra, "review", "review", "Before edit")

    base = SkillManager(base_dir)
    view = base.with_sources([SkillSource("request-scope", extra, 40, layout="flat")])
    assert view.get_skill("review").description == "Before edit"

    # Edit the SKILL.md on disk; the cached view must rescan on next read
    # (same _ensure_fresh fingerprint contract as the base manager).
    review.write_text(
        "---\nname: review\ndescription: After edit\n---\nBody",
        encoding="utf-8",
    )
    os.utime(review, None)

    assert view.get_skill("review").description == "After edit"
    assert base.with_sources([SkillSource("request-scope", extra, 40, layout="flat")]) is view


def test_scope_cache_is_bounded(tmp_path):
    base = SkillManager(tmp_path / "base")

    for index in range(12):
        extra = tmp_path / f"extra-{index}"
        extra.mkdir()
        base.with_sources([SkillSource(f"scope-{index}", extra, 40, layout="flat")])

    assert len(base._scoped_views) <= 8
