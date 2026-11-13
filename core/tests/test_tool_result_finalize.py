"""The tool-result finalizer seam must compose, isolate failures, and be reversible.

The kernel used to apply every output transform inline, so a plugin or a second
consumer could not participate without editing the loop, and nothing could prove
which transform had run. These tests pin the seam's contract: ordered
composition, a raising finalizer skipped rather than fatal, no widening of
authority, and a disposer that actually removes the registration.
"""

from __future__ import annotations

import pytest

from atlas.engine.kernel.tool_finalize import (
    FinalizedOutput,
    FinalizeView,
    ToolResultFinalizers,
    finalize_view,
)

pytestmark = pytest.mark.unit


def _view(name: str = "read_file", is_error: bool = False) -> FinalizeView:
    return FinalizeView(
        call_id="call-1", name=name, arguments={"path": "a.txt"},
        state="failed" if is_error else "completed", is_error=is_error, duration_ms=12,
    )


def _result(content: str = "raw") -> FinalizedOutput:
    return FinalizedOutput(content=content, output={"content": content})


def test_finalizers_run_in_registration_order_and_compose():
    registry = ToolResultFinalizers()
    registry.register("first", lambda r, v: FinalizedOutput(f"[1]{r.content}", r.output))
    registry.register("second", lambda r, v: FinalizedOutput(f"[2]{r.content}", r.output))

    out = registry.apply(_result("x"), _view())

    # The second must see the first's output, not the original.
    assert out.content == "[2][1]x"
    assert out.applied == ["first", "second"]


def test_a_raising_finalizer_is_skipped_not_fatal():
    registry = ToolResultFinalizers()

    def explode(_result, _view):
        raise RuntimeError("plugin bug")

    registry.register("bad", explode)
    registry.register("good", lambda r, v: FinalizedOutput(f"ok:{r.content}", r.output))

    out = registry.apply(_result("x"), _view())

    assert out.content == "ok:x"
    assert out.applied == ["good"]
    assert out.rejected and out.rejected[0][0] == "bad"
    assert "plugin bug" in out.rejected[0][1]


def test_returning_none_means_no_change_and_is_not_counted_as_applied():
    registry = ToolResultFinalizers()
    registry.register("noop", lambda r, v: None)

    out = registry.apply(_result("x"), _view())

    assert out.content == "x"
    assert out.applied == []


def test_registering_the_same_name_replaces_instead_of_stacking():
    registry = ToolResultFinalizers()
    registry.register("redact", lambda r, v: FinalizedOutput("A", r.output))
    registry.register("redact", lambda r, v: FinalizedOutput("B", r.output))

    out = registry.apply(_result("x"), _view())

    assert out.content == "B"
    assert registry.names() == ["redact"]


def test_disposer_removes_the_registration():
    registry = ToolResultFinalizers()
    dispose = registry.register("temp", lambda r, v: FinalizedOutput("changed", r.output))
    assert len(registry) == 1

    dispose()

    assert len(registry) == 0
    assert registry.apply(_result("x"), _view()).content == "x"


def test_anonymous_finalizers_are_rejected_at_registration():
    registry = ToolResultFinalizers()
    with pytest.raises(ValueError):
        registry.register("", lambda r, v: r)
    with pytest.raises(TypeError):
        registry.register("not-callable", "nope")  # type: ignore[arg-type]


def test_view_is_built_from_either_receipt_shape():
    class _Receipt:
        call_id = "c9"
        state = "completed"
        duration_ms = 5
        is_error = False

    from_object = finalize_view(_Receipt(), name="t", arguments={"k": 1})
    from_dict = finalize_view(
        {"call_id": "c9", "state": "completed", "duration_ms": 5, "is_error": False},
        name="t", arguments={"k": 1},
    )

    assert from_object == from_dict
    assert from_object.call_id == "c9" and from_object.name == "t"


def test_finalizer_cannot_change_what_the_view_reports():
    """The view is frozen: a finalizer can transform output but not the facts about the call."""
    view = _view(name="write_file")
    with pytest.raises(Exception):
        view.name = "read_file"  # type: ignore[misc]
