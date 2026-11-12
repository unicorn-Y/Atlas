"""Hook bus mode semantics.

Three modes share one ``emit`` that takes no per-call argument, so the behaviour
that matters is the *combination*: serial ignores return values, waterfall lets a
later handler rewrite what the next one sees, and a run of parallel handlers is
gathered where it sits rather than hoisted to the end. The last point is the one
that silently breaks ordering if someone "simplifies" ``emit``, so it is asserted
by timing-independent observation instead of by wall clock.
"""

from __future__ import annotations

import asyncio

import pytest

from atlas.agent.enrichment import HookBus


def _point() -> str:
    """Any real hook point; the bus rejects names outside its table."""
    from atlas.agent.enrichment import HOOK_POINTS

    return sorted(HOOK_POINTS)[0]


def test_an_unknown_point_is_refused() -> None:
    bus = HookBus()
    with pytest.raises(ValueError):
        bus.register("not.a.hook.point", lambda **kw: None)


def test_an_unknown_mode_is_refused() -> None:
    bus = HookBus()
    with pytest.raises(ValueError):
        bus.register(_point(), lambda **kw: None, mode="broadcast")


def test_serial_handlers_both_run_and_nothing_is_rewritten() -> None:
    bus = HookBus()
    seen: list[str] = []

    async def first(**payload: object) -> dict[str, object]:
        seen.append("first")
        return {"value": "rewritten"}

    async def second(**payload: object) -> None:
        seen.append("second")

    point = _point()
    bus.register(point, first, mode="serial")
    bus.register(point, second, mode="serial")
    errors = asyncio.run(bus.emit(point, value="original"))

    assert errors == []
    assert seen == ["first", "second"]
    # A serial handler's dict is dropped: that is what makes the default safe to
    # hand to every existing registration without changing its meaning.
    assert bus.last_payload["value"] == "original"


def test_waterfall_later_handler_sees_the_earlier_rewrite() -> None:
    bus = HookBus()
    seen: list[str] = []

    async def redact(**payload: object) -> dict[str, object]:
        return {"command": str(payload["command"]).replace("secret", "***")}

    async def observe(**payload: object) -> None:
        seen.append(str(payload["command"]))

    point = _point()
    bus.register(point, redact, mode="waterfall")
    bus.register(point, observe, mode="serial")
    asyncio.run(bus.emit(point, command="run secret now"))

    assert seen == ["run *** now"]
    assert bus.last_payload["command"] == "run *** now"


def test_a_waterfall_handler_returning_none_does_not_blank_the_payload() -> None:
    bus = HookBus()

    async def observer(**payload: object) -> None:
        return None

    point = _point()
    bus.register(point, observer, mode="waterfall")
    asyncio.run(bus.emit(point, keep="me"))
    assert bus.last_payload == {"keep": "me"}


def test_a_failing_handler_is_reported_and_does_not_stop_the_rest() -> None:
    bus = HookBus()
    seen: list[str] = []

    async def broken(**payload: object) -> None:
        raise RuntimeError("hook exploded")

    async def fine(**payload: object) -> None:
        seen.append("fine")

    point = _point()
    bus.register(point, broken, mode="serial")
    bus.register(point, fine, mode="serial")
    errors = asyncio.run(bus.emit(point))

    assert seen == ["fine"]
    assert len(errors) == 1
    assert "hook exploded" in str(errors[0])


def test_parallel_batch_flushes_at_its_own_position() -> None:
    """Ordering: serial A → parallel B → serial C must stay A, B, C.

    If a later refactor hoisted every parallel handler to the end, C would run
    before B and this list would read ``["a", "c", "b"]``. No sleeps are needed —
    the serial handlers record their own position.
    """
    bus = HookBus()
    order: list[str] = []

    async def a(**payload: object) -> None:
        order.append("a")

    async def b(**payload: object) -> None:
        order.append("b")

    async def c(**payload: object) -> None:
        order.append("c")

    point = _point()
    bus.register(point, a, mode="serial")
    bus.register(point, b, mode="parallel")
    bus.register(point, c, mode="serial")
    asyncio.run(bus.emit(point))

    assert order == ["a", "b", "c"]


def test_mode_of_reports_the_registration_mode() -> None:
    bus = HookBus()

    def handler(**payload: object) -> None:
        return None

    point = _point()
    bus.register(point, handler, mode="waterfall")
    assert bus.mode_of(point, handler) == "waterfall"
    # An unregistered handler is serial by default rather than an error, because
    # callers ask this question while iterating.
    assert bus.mode_of(point, lambda **kw: None) == "serial"


def test_unregister_removes_only_the_named_handler() -> None:
    bus = HookBus()
    seen: list[str] = []

    async def keep(**payload: object) -> None:
        seen.append("keep")

    async def drop(**payload: object) -> None:
        seen.append("drop")

    point = _point()
    bus.register(point, keep)
    bus.register(point, drop)
    assert bus.unregister(point, drop) is True
    assert bus.unregister(point, drop) is False
    asyncio.run(bus.emit(point))

    assert seen == ["keep"]


def test_forget_owner_drops_only_that_plugins_hooks() -> None:
    """The plugin hot-reload path: identity cannot find a previous generation."""

    bus = HookBus()
    seen: list[str] = []

    async def mine(**payload: object) -> None:
        seen.append("mine")

    async def theirs(**payload: object) -> None:
        seen.append("theirs")

    mine.__atlas_owner__ = "plugin:demo"  # type: ignore[attr-defined]

    point = _point()
    bus.register(point, mine)
    bus.register(point, theirs)
    assert bus.forget_owner("plugin:demo") == 1
    assert bus.forget_owner("") == 0
    asyncio.run(bus.emit(point))

    assert seen == ["theirs"]
