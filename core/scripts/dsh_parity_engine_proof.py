"""Engine-level proof that the plan-mode and scheduler changes reach the real paths.

No model is involved: this drives the same code the kernel uses and prints what
each layer produced. It exists because the configured model channels return
``INSUFFICIENT_BALANCE`` / ``401``, so a real turn cannot complete today; that is
an account problem, and this script is what can still be verified offline.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas import approval_outcome
from atlas.engine.kernel.plan import PlanMode
from atlas.engine.kernel.tools import ToolScheduler


class _Ctx:
    __slots__ = ("mode", "plan_state")

    def __init__(self) -> None:
        self.mode = "act"
        self.plan_state = None


async def _scheduler_proof() -> None:
    events: list[str] = []

    async def dispatch(call_id, name, args):
        events.append(f"start:{call_id}")
        await asyncio.sleep(0.02)
        events.append(f"end:{call_id}")
        return {"data": call_id}

    scheduler = ToolScheduler(dispatch, read_only=lambda name, args: name == "read_file")
    calls = [
        {"id": "r1", "function": {"name": "read_file", "arguments": {"path": "a"}}},
        {"id": "w1", "function": {"name": "local_file", "arguments": {"action": "write", "path": "b"}}},
        {"id": "r2", "function": {"name": "read_file", "arguments": {"path": "c"}}},
    ]
    results = await scheduler.run(calls)
    print("[scheduler] order     :", " ".join(events))
    print("[scheduler] receipts  :", [(r.call_id, r.receipt.state) for r in results])
    print("[scheduler] write full barrier:", events.index("end:w1") < events.index("start:r2"))


def _plan_proof() -> None:
    ctx = _Ctx()
    plan = PlanMode(ctx, {}, plan_update_callback=lambda snapshot: None)
    print("[plan] active before      :", plan.active)
    plan.enter()
    print("[plan] after enter        :", plan.active, "| ctx.mode =", ctx.mode)
    print("[plan] guidance first line:", plan.prompt().splitlines()[0])
    tools = [
        {"type": "function", "function": {"name": "read_file"}},
        {"type": "function", "function": {"name": "write_file"}},
    ]
    print("[plan] allowed tools      :", [t["function"]["name"] for t in plan.filter_tools(tools)])
    plan.approve(user_approved=True)
    print("[plan] after approve      :", plan.active, "| ctx.mode =", ctx.mode)


def _approval_proof() -> None:
    samples = ["allow", "allow_once", "deny", None, "cancel", "who-knows"]
    for value in samples:
        outcome = approval_outcome.normalize(value)
        print(f"[approval] {str(value):<12} -> {outcome:<14} reason={approval_outcome.denial_reason(outcome, tool='Write')[:60] or '(none)'}")


async def main() -> int:
    _plan_proof()
    _approval_proof()
    await _scheduler_proof()

    from atlas.engine.state.atlas_state_common import SCHEMA_VERSION
    from atlas.engine.state.atlas_state_errors import SchemaTooNewError

    print(f"[schema] build supports version {SCHEMA_VERSION}; newer stores raise "
          f"{SchemaTooNewError.__name__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
