"""Live check: one real model turn through the kernel, plus the export round trip.

Run against the real Atlas data root and the configured model. Prints what it
saw; it never reads or prints credential values (the model manager owns them).
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas import approval_outcome
from atlas.engine.kernel.plan import PlanMode


async def main() -> int:
    from atlas.agent import get_agent
    from atlas.config import DATA_ROOT
    from atlas.engine.session_sync import _open_db

    def _plan_probe() -> None:
        class Ctx:
            __slots__ = ("mode", "plan_state")
            def __init__(self):
                self.mode = "act"
                self.plan_state = None

        ctx = Ctx()
        plan = PlanMode(ctx, {}, plan_update_callback=lambda s: None)
        print(f"plan.active(before)={plan.active}")
        plan.enter()
        print(f"plan.active(after)={plan.active} ctx.mode={ctx.mode}")
        print(f"plan.prompt()[:48]={plan.prompt()[:48]!r}")
        plan.approve(user_approved=True)
        print(f"plan.active(approved)={plan.active} ctx.mode={ctx.mode}")

    _plan_probe()
    print("approval normalize:",
          {k: approval_outcome.normalize(k) for k in
           ("allow", "deny", None, "cancel", "weird-value")})

    agent = get_agent()
    manager = agent._model_mgr
    model = manager.current_model
    print(f"model={model}")

    session_id = f"live-check-{uuid.uuid4().hex[:8]}"
    messages = [
        {"role": "system", "content": "Reply with exactly the word: OK"},
        {"role": "user", "content": "Reply with exactly the word: OK"},
    ]
    from atlas.engine.kernel.model_call import complete_stream

    result = await complete_stream(
        agent, model, messages, [], max_output_tokens=16, max_retries=1,
    )
    text = (result.content or "").strip()
    usage = result.usage if isinstance(result.usage, dict) else {}
    print(f"live reply={text!r}")
    print(f"usage input={usage.get('prompt_tokens')} output={usage.get('completion_tokens')}")
    print(f"attempts={result.attempts}")

    home = DATA_ROOT / "engine"
    if (home / "state.db").exists():
        with _open_db(home) as db:
            sessions = db.search_sessions(limit=3)
        if sessions:
            sid = sessions[0]["id"]
            with _open_db(home) as db:
                doc = db.export_session(sid)
            print(f"export session={sid} messages={len(doc.get('messages') or [])} "
                  f"title={str(doc.get('title'))[:30]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
