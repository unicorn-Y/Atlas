"""The wire event contract, checked against both frontend files.

The bug this test is built around is that a missing event name is **not** a
compile error. ``runtimeEvents.ts`` keeps a ``known`` set and
:func:`normalizeRuntimeEvent` ends with ``if (!known.has(envelope.event)) return
null`` — the frame is dropped in silence. ``subtask.steered`` and
``subtask.steer_rejected`` were handled in ``ConversationActivity.tsx`` and
present in the ``AgentEventType`` union, yet absent from ``known``, so the
"已送达 / 被拒绝" feedback after steering a sub-agent could never appear on
screen no matter what the backend sent.

Three names of truth therefore have to agree, and only two of the three are
Python-checkable from here:

* :mod:`atlas.api.event_names` — the backend's declaration (this module);
* ``frontend/src/renderer/services/runtimeEvents.ts`` — the ``known`` set that
  decides whether a frame survives;
* ``frontend/src/types/runtime.ts`` — the ``AgentEventType`` union that decides
  whether the timeline can handle it.

The two frontend files are parsed as text rather than compiled, because a test
that needs node + a bundler is a test that gets skipped. Both are plain sets of
single-quoted dotted literals, so a regex is exact here, not a shortcut.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from atlas.api import event_names

#: ``core/tests/test_event_contract.py`` → repo root. Same hop conftest.py uses.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_EVENTS_TS = _REPO_ROOT / "frontend/src/renderer/services/runtimeEvents.ts"
_RUNTIME_TS = _REPO_ROOT / "frontend/src/types/runtime.ts"

#: A dotted lower-case wire name: ``run.started``, ``goal.continuation``,
#: ``run.steer.rejected``. Anchored on the quotes so CSS classes, imports and
#: prose cannot be mistaken for event names.
_DOTTED = re.compile(r"'([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)'")


def _literals(path: Path) -> set[str]:
    return set(_DOTTED.findall(path.read_text(encoding="utf-8")))


@pytest.mark.unit
def test_both_frontend_files_exist() -> None:
    """A path typo would make every other assertion vacuously pass.

    ``_literals`` on a missing file raises, but the failure would read as an
    IOError in an unrelated test. Asserting presence first keeps the diagnosis
    attached to the path that is actually wrong.
    """
    assert _RUNTIME_EVENTS_TS.is_file(), f"缺少 {_RUNTIME_EVENTS_TS}"
    assert _RUNTIME_TS.is_file(), f"缺少 {_RUNTIME_TS}"


@pytest.mark.unit
def test_renderer_known_set_matches_event_names() -> None:
    """``runtimeEvents.ts`` must know exactly the renderer events — no more, no less.

    Too few is the dangerous direction: a frame Atlas sends is dropped before it
    reaches any component. Too many means the renderer keeps a name nothing
    emits, which is how the set accumulated its previous drift.
    """
    known = _literals(_RUNTIME_EVENTS_TS)
    expected = set(event_names.RENDERER_EVENTS)

    missing = sorted(expected - known)
    extra = sorted(known - expected)
    assert not missing, (
        "runtimeEvents.ts 的 known 集合缺少这些事件，后端发出去会被静默丢弃："
        f"{missing}"
    )
    assert not extra, (
        "runtimeEvents.ts 的 known 集合多出这些名字，没有任何后端生产者："
        f"{extra}"
    )


@pytest.mark.unit
def test_agent_event_type_union_matches_event_names() -> None:
    """The TS union must cover every emitted name a component can be handed.

    ``artifact.created`` is the one permitted exception, and it is permitted in
    the *union* direction only: it is a real backend frame that
    ``normalizeRuntimeEvent`` rewrites into ``artifact.updated`` before it is
    typed, so it never appears as an ``AgentEventType``. The test asserts that
    rewrite still exists rather than hard-coding an allowance that would survive
    the rewrite being deleted.
    """
    union = _literals(_RUNTIME_TS)
    expected = set(event_names.TYPED_EVENTS)

    missing = sorted(expected - union)
    assert not missing, f"AgentEventType 缺少这些事件类型：{missing}"

    for rewritten in event_names.REWRITTEN_EVENTS:
        assert rewritten in event_names.RENDERER_EVENTS, (
            f"{rewritten} 必须留在 known 里，否则这一帧会被静默丢弃。"
        )
        assert rewritten not in union, (
            f"{rewritten} 会被 runtimeEvents.ts 改写成别的类型，不该出现在 "
            "AgentEventType 里。"
        )

    # The synthesis must still be present, otherwise artifact.created (a real
    # backend frame) is filtered out by `known` and office documents vanish.
    source = _RUNTIME_EVENTS_TS.read_text(encoding="utf-8")
    assert "artifact.created" in source and "artifact.updated" in source, (
        "runtimeEvents.ts 里 artifact.created → artifact.updated 的转写不见了；"
        "生成文档的卡片会整类消失。"
    )


@pytest.mark.unit
def test_typed_events_is_renderer_minus_rewrites() -> None:
    """``TYPED_EVENTS`` is derived from the two real lists, never hand-kept."""
    assert set(event_names.TYPED_EVENTS) == (
        set(event_names.RENDERER_EVENTS) - set(event_names.REWRITTEN_EVENTS)
    )
    assert set(event_names.REWRITTEN_EVENTS) <= set(event_names.RENDERER_EVENTS)


@pytest.mark.unit
def test_desktop_and_derived_partition_renderer() -> None:
    """``RENDERER_EVENTS`` is derived, so a name can never be half-registered."""
    assert set(event_names.RENDERER_EVENTS) == (
        set(event_names.DESKTOP_EVENTS) | set(event_names.DERIVED_EVENTS)
    )
    assert not (set(event_names.DESKTOP_EVENTS) & set(event_names.DERIVED_EVENTS)), (
        "desktop 与 derived 必须互斥：一个是后端真实发出，一个是渲染层合成。"
    )


@pytest.mark.unit
def test_no_duplicate_names_in_any_channel() -> None:
    """Duplicate literals hide a lost name: a typo reads as a present entry."""
    for label, names in (
        ("desktop", event_names.DESKTOP_EVENTS),
        ("derived", event_names.DERIVED_EVENTS),
        ("cli", event_names.CLI_EVENTS),
    ):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        assert not duplicates, f"{label} 里有重复的事件名：{duplicates}"


@pytest.mark.unit
def test_cli_events_never_reach_the_renderer() -> None:
    """``turn.*`` / ``item.*`` / ``atlas.result`` are terminal-repl frames.

    They are in ``ALL_EVENTS`` because Atlas emits them, but they must not be in
    ``RENDERER_EVENTS``: if one ever appeared on the run socket the renderer has
    no component for it, and the union check above would start demanding a type
    for a frame that never arrives.
    """
    leaked = sorted(set(event_names.CLI_EVENTS) & set(event_names.RENDERER_EVENTS))
    assert not leaked, f"CLI 事件不该出现在渲染层名单里：{leaked}"
    assert set(event_names.ALL_EVENTS) == (
        set(event_names.RENDERER_EVENTS) | set(event_names.CLI_EVENTS)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "name",
    [
        # The steering pair: handled in the UI, missing from `known` — the bug.
        "subtask.steered",
        "subtask.steer_rejected",
        # Goal loop: emitted by run_drive, unlistened until the timeline gained
        # its `goal` notice case.
        "goal.updated",
        "goal.continuation",
        "run.steer.rejected",
    ],
)
def test_previously_dropped_events_are_registered(name: str) -> None:
    """Regression guard for the exact names that used to be dropped."""
    assert event_names.is_renderer_event(name)
    assert name in _literals(_RUNTIME_EVENTS_TS)


@pytest.mark.unit
def test_is_renderer_event_rejects_unknown_and_cli() -> None:
    assert event_names.is_renderer_event("run.started")
    assert not event_names.is_renderer_event("turn.started")
    assert not event_names.is_renderer_event("not.a.real.event")
    assert event_names.sorted_renderer_events() == sorted(event_names.RENDERER_EVENTS)
