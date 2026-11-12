"""Introspection provider: the wire event contract.

Before :mod:`atlas.api.event_names` existed, the set of event names was spread
across four places that had to agree and had no way to check that they did: the
emitters in ``run_drive.py``, the passthrough allowlist, the reducer's ``known``
set in ``frontend/src/renderer/services/runtimeEvents.ts``, and the
``AgentEventType`` union in ``frontend/src/types/runtime.ts``.

They did not agree. Sixteen names the backend emitted were absent from the
renderer's ``known`` set, and ``runtimeEvents`` silently drops any envelope whose
event is not known — so the events vanished with no error, no log, and no UI
symptom distinguishable from "the feature never fired". Sub-task steering
feedback was lost this way, and so were goal notices.

This provider exposes the contract as data so a mismatch can be *asked about*
instead of rediscovered: the canonical list, plus the channel each name travels
on, because "unknown event" has a different meaning per channel (a UI bug vs. a
CLI-only name that has no renderer consumer by design).
"""

from __future__ import annotations

from typing import Any

from atlas.introspect.registry import Context, Method, Provider, object_schema


def _names() -> Any:
    from atlas.api import event_names

    return event_names


def _summary(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    names = _names()
    return {
        "desktop": len(names.DESKTOP_EVENTS),
        "derived": list(names.DERIVED_EVENTS),
        "rewritten": list(names.REWRITTEN_EVENTS),
        "renderer": len(names.RENDERER_EVENTS),
        "typed": len(names.TYPED_EVENTS),
        "cli": list(names.CLI_EVENTS),
        "all": len(names.ALL_EVENTS),
    }


def _list_events(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    names = _names()
    channel = str(args.get("channel") or "").strip().lower()
    search = str(args.get("search") or "").strip().lower()

    rows = []
    if channel in ("", "desktop"):
        rows += [{"event": name, "channel": "desktop"} for name in names.DESKTOP_EVENTS]
    if channel in ("", "derived"):
        rows += [{"event": name, "channel": "derived"} for name in names.DERIVED_EVENTS]
    if channel in ("", "cli"):
        rows += [{"event": name, "channel": "cli"} for name in names.CLI_EVENTS]
    if channel == "typed":
        rows = [{"event": name, "channel": "typed"} for name in sorted(names.TYPED_EVENTS)]
    if search:
        rows = [row for row in rows if search in row["event"]]
    return {"count": len(rows), "events": rows}


def _describe_event(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    names = _names()
    event = args["event"]
    if event in names.DERIVED_EVENTS:
        channel, renders = "derived", True
    elif event in names.REWRITTEN_EVENTS:
        channel, renders = "rewritten", True
    elif event in names.DESKTOP_EVENTS:
        channel, renders = "desktop", True
    elif event in names.CLI_EVENTS:
        channel, renders = "cli", False
    else:
        raise KeyError(f"事件契约里没有 {event!r}")
    return {
        "event": event,
        "channel": channel,
        "renderer_visible": renders,
        "is_renderer_event": names.is_renderer_event(event),
        # A rewritten frame keeps its place in `known` but is never handed to a
        # component under its own name: it changes identity first. Reporting the
        # typed flag separately stops "renders: true" from being read as "the
        # timeline has a case for this literal", which it does not.
        "is_typed_event": event in names.TYPED_EVENTS,
    }


def _by_prefix(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """Group by the dotted prefix — the de-facto namespace each subsystem owns."""
    names = _names()
    groups: dict[str, list[str]] = {}
    for name in names.sorted_renderer_events():
        prefix = name.split(".", 1)[0]
        groups.setdefault(prefix, []).append(name)
    return {
        "count": len(groups),
        "namespaces": [
            {"namespace": prefix, "events": events, "count": len(events)}
            for prefix, events in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        ],
    }


def _hook_modes(ctx: Context, args: dict[str, Any]) -> dict[str, Any]:
    """How lifecycle hooks combine: which points exist, and what each mode means.

    ``HookBus`` supports three modes and the choice is invisible from the call
    site — ``emit`` reads each handler's registered mode instead of taking one per
    call. That keeps call sites unchanged, but it also means "why did my hook not
    see what the previous one returned" has no answer anywhere except the class
    docstring. This turns the semantics into data.
    """
    from atlas.agent.enrichment import _HOOK_MODES, HOOK_POINTS

    return {
        "points": list(HOOK_POINTS),
        "point_count": len(list(HOOK_POINTS)),
        "modes": list(_HOOK_MODES),
        "semantics": {
            "serial": "按注册顺序逐个执行，返回值被忽略——审计/遥测形状，也是默认值。",
            "waterfall": "返回 dict 的处理器会把自己的结果合并进 payload，后者能看到前者的改写。",
            "parallel": "连续注册的 parallel 处理器合批并发执行，返回值被忽略；"
                        "批在它原来的位置上刷新，不会把所有并发处理器挪到最后。",
        },
        "notes": [
            "任一处理器抛错只记录进返回值，绝不阻断 Agent。",
            "改写结果同时留在 bus.last_payload，调用点可据此读到变化。",
            "插件热更靠 forget_owner 按 __atlas_owner__ 清钩子，靠 identity 会漏删。",
        ],
    }


PROVIDER = Provider(
    id="events",
    title="事件契约",
    summary="桌面端事件名的唯一真源：有哪些、走哪条通道、渲染层是否应当看见。",
    methods=(
        Method(
            name="summary",
            summary="各通道的事件数量。",
            input_schema=object_schema(),
            run=_summary,
        ),
        Method(
            name="list",
            summary="列出事件名，可按通道或关键字筛选。",
            input_schema=object_schema(
                {
                    "channel": {"type": "string", "description": "desktop / derived / cli。"},
                    "search": {"type": "string", "description": "事件名子串。"},
                }
            ),
            run=_list_events,
        ),
        Method(
            name="describe",
            summary="看单个事件走哪条通道、渲染层是否可见。",
            input_schema=object_schema(
                {"event": {"type": "string", "description": "事件名。"}}, required=("event",)
            ),
            run=_describe_event,
        ),
        Method(
            name="namespaces",
            summary="按前缀分组，看每个子系统占了多少事件。",
            input_schema=object_schema(),
            run=_by_prefix,
        ),
        Method(
            name="hooks",
            summary="生命周期钩子总线的模式语义：serial / waterfall / parallel 各自意味着什么。",
            input_schema=object_schema(),
            run=_hook_modes,
        ),
    ),
)
