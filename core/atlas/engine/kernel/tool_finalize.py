"""A seam for transforming a tool result before the model sees it.

Every output transformation used to live inline in the kernel loop: truncation,
hook-supplied context, image extraction, per-tool special cases. That made three
things impossible without editing the loop again:

* a plugin that wants to redact or annotate a result,
* a per-tool finalizer owned by the tool definition rather than the loop,
* a test that proves what the model actually received.

This module is the seam. A finalizer is a pure function of the result plus a
small immutable view of the call, and it returns either the same result or a
replacement. Finalizers run in registration order and each sees the previous
one's output, so a redaction pass and a truncation pass compose without either
knowing about the other.

Design constraints, chosen to keep the loop's behaviour unchanged when no
finalizer is registered:

* a finalizer may not raise — a broken one is skipped and reported, because a
  plugin must never turn a successful tool call into a crash;
* a finalizer may not add images or change ``outcome``; it is a content
  transform. Widening authority here would let a plugin silently upgrade a
  denied call;
* registration returns a disposer, so a plugin unload actually removes it.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from typing import Any, Callable, Final

log = structlog.get_logger()

#: Fields a finalizer is allowed to change. Anything else is ignored, so a buggy
#: finalizer cannot rewrite the receipt, the call id, or the outcome.
MUTABLE_FIELDS: Final[frozenset[str]] = frozenset({"content", "data", "is_error"})


@dataclass(frozen=True, slots=True)
class FinalizeView:
    """The immutable facts a finalizer may inspect about the call."""

    call_id: str
    name: str
    arguments: dict[str, Any]
    state: str
    is_error: bool
    duration_ms: int


@dataclass(slots=True)
class FinalizedOutput:
    """What the loop actually hands to the model and to the UI."""

    content: str
    output: Any
    applied: list[str] = field(default_factory=list)
    rejected: list[tuple[str, str]] = field(default_factory=list)


Finalizer = Callable[[FinalizedOutput, FinalizeView], FinalizedOutput | None]


class ToolResultFinalizers:
    """Ordered registry of result finalizers, with reversible registration."""

    def __init__(self) -> None:
        self._entries: list[tuple[str, Finalizer]] = []

    def register(self, name: str, finalizer: Finalizer) -> Callable[[], None]:
        """Add a finalizer and return the disposer that removes it.

        Registering the same name twice replaces the earlier one rather than
        stacking, so a reload cannot silently double-apply a transform.
        """
        key = str(name or "").strip()
        if not key:
            raise ValueError("A tool-result finalizer needs a name")
        if not callable(finalizer):
            raise TypeError(f"Finalizer {key!r} is not callable")
        self.remove(key)
        self._entries.append((key, finalizer))

        def dispose() -> None:
            self.remove(key)

        return dispose

    def remove(self, name: str) -> bool:
        key = str(name or "").strip()
        before = len(self._entries)
        self._entries = [entry for entry in self._entries if entry[0] != key]
        return len(self._entries) != before

    def names(self) -> list[str]:
        return [name for name, _ in self._entries]

    def __len__(self) -> int:
        return len(self._entries)

    def apply(self, result: FinalizedOutput, view: FinalizeView) -> FinalizedOutput:
        """Run every finalizer in order; a raising one is skipped, not fatal."""
        current = result
        for name, finalizer in list(self._entries):
            try:
                candidate = finalizer(current, view)
            except Exception as exc:  # noqa: BLE001 - a plugin must not break a call
                log.warning("tool_finalizer_failed", finalizer=name, tool=view.name,
                            reason=f"{type(exc).__name__}: {exc}")
                current.rejected.append((name, f"{type(exc).__name__}: {exc}"))
                continue
            if candidate is None:
                continue
            current = _merge(current, candidate)
            current.applied.append(name)
        return current


def _merge(base: FinalizedOutput, candidate: FinalizedOutput) -> FinalizedOutput:
    """Take the candidate's mutable fields and keep the accumulated bookkeeping.

    A finalizer constructs a new ``FinalizedOutput`` in the normal case, which
    would drop the earlier ``applied``/``rejected`` lists; the merge keeps that
    history so a caller can report exactly which transforms ran.
    """
    return FinalizedOutput(
        content=candidate.content,
        output=candidate.output,
        applied=list(base.applied),
        rejected=list(base.rejected),
    )


def finalize_view(receipt: Any, *, name: str, arguments: dict[str, Any],
                  call_id: str = "") -> FinalizeView:
    """Build the view from whatever receipt shape the scheduler produced."""
    def _get(key: str, default: Any = None) -> Any:
        if isinstance(receipt, dict):
            return receipt.get(key, default)
        return getattr(receipt, key, default)

    return FinalizeView(
        call_id=str(call_id or _get("call_id", "") or ""),
        name=str(name),
        arguments=dict(arguments or {}),
        state=str(_get("state", "") or ""),
        is_error=bool(_get("is_error", False)),
        duration_ms=int(_get("duration_ms", 0) or 0),
    )