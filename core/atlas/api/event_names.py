"""The wire event names Atlas emits, in one place.

Before this module the event contract lived in three places that could drift
apart silently, and did:

* :mod:`atlas.api.run_drive` and friends called ``emit("literal", ...)`` — 58
  distinct literals, discoverable only by grepping;
* ``frontend/src/renderer/services/runtimeEvents.ts`` kept a hand-written
  ``known`` set; :func:`parseEnvelope` drops anything missing from it with a
  bare ``return null``;
* ``frontend/src/types/runtime.ts`` repeated the same names as a TS union.

A name missing from the frontend set is not a compile error — it is a *silent
drop at runtime*. ``subtask.steered`` and ``subtask.steer_rejected`` were
handled in ``ConversationActivity.tsx:322`` and present in the ``AgentEventType``
union, yet absent from ``known``, so the user's "已送达 / 被拒绝" feedback after
steering a sub-agent could never appear. That is the failure mode this module
exists to make impossible.

Three channels, kept apart because they are genuinely different contracts:

``desktop``
    Frames that reach the renderer over the run WebSocket. Everything here
    must exist in the frontend ``known`` set.
``derived``
    Shapes the renderer synthesises from another frame (``artifact.created`` →
    ``artifact.updated``). They have no backend producer *by design*; listing
    them here stops the drift check from calling them orphans.
``cli``
    Terminal-repl frames (``turn.*``, ``item.*``, ``atlas.result``,
    ``skills.preloaded``) that never cross the WebSocket.

The consistency test ``core/tests/test_event_contract.py`` parses the two
frontend files and fails when either side gains or loses a name.
"""

from __future__ import annotations

from typing import Final

#: Frames delivered to the desktop renderer over ``/ws``. Order is presentation
#: order and is not otherwise meaningful.
DESKTOP_EVENTS: Final[tuple[str, ...]] = (
    "run.started",
    "run.status",
    "run.phase",
    "run.background",
    "run.paused",
    "run.resumed",
    "run.steered",
    "run.steer.rejected",
    "run.usage",
    "run.todos",
    "run.plan.proposed",
    "run.plan.updated",
    "run.model_switched",
    "run.verify_nudge",
    "run.compaction.progress",
    "run.recovery.notice",
    "run.context.sources",
    "run.context.warning",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "message.delta",
    "message.rollback",
    "message.completed",
    "tool.preparing",
    "tool.started",
    "tool.output",
    "tool.completed",
    "approval.required",
    "approval.responded",
    "artifact.created",
    "input.required",
    "check.results",
    "rules.loaded",
    "rules.trust_required",
    "hook.ran",
    "session.title",
    "context.window.switched",
    "chapter.marked",
    "lsp.diagnostics",
    "review.findings",
    "safety.reviewed",
    "moa.references",
    "process.completed",
    "process.notification",
    "mcp.startup.progress",
    "media.ocr.progress",
    "canvas.update",
    "component.push",
    "subtask.started",
    "subtask.progress",
    "subtask.output",
    "subtask.completed",
    "subtask.group_completed",
    "subtask.background_completed",
    "subtask.steered",
    "subtask.steer_rejected",
    # X2 computer control: foreground confirmation, resume, and every step.
    "computer.foreground_required",
    "computer.foreground_resumed",
    "computer.foreground_denied",
    "computer.step",
    "computer.frame",
    # X2 browser agent: handoff, panel address sync, recorded steps.
    "browser.handoff_required",
    "browser.handoff_resolved",
    "browser.panel.sync",
    "browser.step",
    "browser.artifact",
    "browser.vault_fill_denied",
    # Goal loop: the judge's verdict and its continuation hand-off. Emitted by
    # ``run_drive`` since the goal loop landed; unlistened in the renderer until
    # the timeline gained its ``goal`` notice case.
    "goal.updated",
    "goal.continuation",
)

#: Frames the renderer *keeps* but never surfaces under their own name: they are
#: rewritten into another typed event before a component ever sees them.
#: ``artifact.created`` is the only one — ``runtimeEvents.ts`` turns it into
#: ``artifact.updated`` so office documents and generated files share the
#: artifact card. They belong in ``known`` (dropping the frame would lose the
#: whole card) and in ``DESKTOP_EVENTS`` (a backend really emits it), but they
#: must **not** appear in the ``AgentEventType`` union, because nothing ever
#: reaches a component with that type.
REWRITTEN_EVENTS: Final[tuple[str, ...]] = ("artifact.created",)

#: Synthesised in the renderer, no backend producer. ``artifact.updated`` is
#: built from ``artifact.created`` by ``runtimeEvents.ts`` so office documents
#: and generated files share the artifact card.
DERIVED_EVENTS: Final[tuple[str, ...]] = ("artifact.updated",)

#: Terminal-repl frames. Never sent over the WebSocket.
CLI_EVENTS: Final[tuple[str, ...]] = (
    "turn.started",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "item.started",
    "item.completed",
    "atlas.result",
    "skills.preloaded",
)

#: Every name the renderer is allowed to keep. ``runtimeEvents.ts`` compares
#: against exactly this set.
RENDERER_EVENTS: Final[frozenset[str]] = (
    frozenset(DESKTOP_EVENTS) | frozenset(DERIVED_EVENTS)
)

#: Every name that can appear as an ``AgentEventType`` — i.e. every name a
#: component may be asked to render. This is ``RENDERER_EVENTS`` minus the
#: rewritten frames, which change identity before they are typed.
TYPED_EVENTS: Final[frozenset[str]] = RENDERER_EVENTS - frozenset(REWRITTEN_EVENTS)

#: Every name Atlas can emit anywhere.
ALL_EVENTS: Final[frozenset[str]] = RENDERER_EVENTS | frozenset(CLI_EVENTS)


def is_renderer_event(name: str) -> bool:
    """True when ``name`` should survive :func:`parseEnvelope`."""
    return name in RENDERER_EVENTS


def sorted_renderer_events() -> list[str]:
    """Stable alphabetical order, for tests and for operator-facing listings."""
    return sorted(RENDERER_EVENTS)
