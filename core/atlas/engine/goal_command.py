"""The CLI's /goal semantics, shared by every goal command surface.

Adapters supply authorization and schedule the returned prompt; this module alone
parses subcommands and mutates goal state. It never changes conversation history.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from atlas.engine import goals

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoalCommandResult:
    output: str
    prompt: str | None = None
    kickoff: bool = False
    clear_pending: str | None = None
    error: bool = False


def _english(key, default, **values):
    return default.format(**values)


def _status(mgr, arg, render):
    return GoalCommandResult(mgr.status_line())


def _show(mgr, arg, render):
    return GoalCommandResult(f"{mgr.status_line()}\n{mgr.render_contract()}")


def _pause(mgr, arg, render):
    state = mgr.pause(reason="user-paused")
    return GoalCommandResult(
        render("gateway.goal.paused", "⏸ Goal paused: {goal}", goal=state.goal) if state
        else render("gateway.goal.no_goal_set", "No goal set."),
        clear_pending="pause" if state else None,
    )


def _resume(mgr, arg, render):
    state = mgr.resume()
    if state is None:
        return GoalCommandResult(render("gateway.goal.no_resume", "No goal to resume."))
    return GoalCommandResult(render("gateway.goal.resumed", "▶ Goal resumed: {goal}", goal=state.goal),
                             prompt=mgr.next_continuation_prompt())


def _clear(mgr, arg, render):
    had = mgr.has_goal()
    mgr.clear()
    return GoalCommandResult(render("gateway.goal_cleared", "✓ Goal cleared.") if had else
                             render("gateway.no_active_goal", "No active goal."), clear_pending="clear")


def _unwait(mgr, arg, render):
    return GoalCommandResult("▶ Wait barrier cleared — goal loop resumes." if mgr.stop_waiting()
                             else "No wait barrier set.")


def _wait(mgr, arg):
    if not arg:
        return GoalCommandResult("Usage: /goal wait <pid> [reason]", error=True)
    tokens = arg.split(None, 1)
    try:
        pid = int(tokens[0])
    except ValueError:
        return GoalCommandResult("/goal wait: <pid> must be an integer process id.", error=True)
    reason = tokens[1].strip() if len(tokens) > 1 else ""
    mgr.wait_on(pid, reason=reason)
    suffix = f" ({reason})" if reason else ""
    return GoalCommandResult(f"⏳ Goal parked on pid {pid}{suffix}. Loop pauses until it exits.")


def _gate_add(mgr, arg):
    gate = mgr.add_gate(arg)
    return GoalCommandResult(f"⚿ Gate added: $ {gate.command} "
                             f"({gate.max_retries} retries, {gate.timeout_seconds}s timeout). "
                             "It must pass before the goal can complete.")


def _gate_remove(mgr, arg):
    return GoalCommandResult(f"✓ Gate removed: $ {mgr.remove_gate(int(arg))}")


def _gate_clear(mgr, arg):
    count = mgr.clear_gates()
    return GoalCommandResult(f"✓ Cleared {count} gate{'s' if count != 1 else ''}.")


def _subgoal(mgr, arg):
    if not mgr.has_goal():
        return GoalCommandResult("/goal subgoal: set a goal first.", error=True)
    if not arg or arg.lower() == "list":
        return GoalCommandResult(mgr.render_subgoals())
    verb, _, rest = arg.partition(" ")
    verb, rest = verb.lower(), rest.strip()
    if verb == "add" and rest:
        index = len(mgr.state.subgoals) + 1
        item = mgr.add_subgoal(rest)
        return GoalCommandResult(f"✓ Subgoal {index} saved: {item}")
    if verb in {"remove", "rm"} and rest.isdigit():
        item = mgr.remove_subgoal(int(rest))
        return GoalCommandResult(f"✓ Removed subgoal {rest}: {item}")
    if verb == "edit":
        index, separator, text = rest.partition(" ")
        if separator and index.isdigit() and text.strip():
            item = mgr.edit_subgoal(int(index), text)
            return GoalCommandResult(f"✓ Updated subgoal {index}: {item}")
    if verb in {"done", "complete", "reopen"} and rest.isdigit():
        item = mgr.complete_subgoal(int(rest), completed=verb != "reopen")
        return GoalCommandResult(f"{'✓ Completed' if verb != 'reopen' else '↻ Reopened'} subgoal {rest}: {item}")
    if verb == "clear" and not rest:
        count = mgr.clear_subgoals()
        return GoalCommandResult(f"✓ Cleared {count} subgoal(s).")
    return GoalCommandResult("Usage: /goal subgoal [list | add <text> | edit <N> <text> | remove <N> | done <N> | reopen <N> | clear]", error=True)


def _plan(mgr, arg):
    """Inspect or relax the decomposition gate on the active goal."""
    if not mgr.has_goal():
        return GoalCommandResult("/goal plan: set a goal first.", error=True)
    state = mgr.state
    verb = arg.strip().lower()
    if verb in {"off", "free", "skip"}:
        if not state.subgoals and state.status == "active":
            state.decomposition_required = False
            mgr._save()
            return GoalCommandResult(
                "✓ Plan gate off: this goal will run without a saved milestone list. "
                "Turn it back on with /goal plan on."
            )
        return GoalCommandResult("Plan gate only applies to a goal with no milestones.")
    if verb in {"on", "require"}:
        state.decomposition_required = True
        mgr._save()
        return GoalCommandResult("✓ Plan gate on: the next turn must save milestones before implementing.")
    lines = [f"Plan gate: {'required' if state.decomposition_required else 'off'}"]
    if state.needs_plan():
        lines.append("Status: the next turn will be a planning turn (no milestones saved yet).")
    elif state.subgoals:
        done = len(state.completed_subgoals)
        lines.append(f"Milestones: {done}/{len(state.subgoals)} complete")
        for index, text in enumerate(state.subgoals, 1):
            mark = "x" if index in state.completed_subgoals else " "
            lines.append(f"  - [{mark}] {index}. {text}")
    else:
        lines.append("Status: no milestones, but the gate is off.")
    return GoalCommandResult("\n".join(lines))


def _stranded(mgr, arg, render):
    """List goals left active by a restart, and how to pick one back up.

    A goal this session already owns is excluded: it is not stranded, it is
    running, and offering it back would invite a second driver.
    """
    from atlas.engine.goal_loop import scan_resumable_goals, summarize

    home = getattr(mgr, "home", None)
    others = [g for g in scan_resumable_goals(home) if g.session_id != mgr.session_id]
    if not others:
        return GoalCommandResult(
            render("gateway.goal.no_stranded", "No goals were left stranded by a restart."))
    counts = summarize(others)
    lines = [
        render("gateway.goal.stranded_header",
               "{count} goal(s) survived a restart but no process is advancing them:",
               count=counts["resumable"]),
    ]
    for goal in others:
        remaining = " · ".join(goal.remaining_subgoals[:3]) or "—"
        left = len(goal.remaining_subgoals)
        lines.append(
            f"  • {goal.session_id}  {goal.goal[:60]}\n"
            f"    {goal.reason}; {left} subgoal(s) left: {remaining}"
        )
    lines.append(
        render("gateway.goal.stranded_hint",
               "Resume one with /goal resume-other <session_id>, or in the UI via "
               "GET /api/engine-goals/stranded."))
    return GoalCommandResult("\n".join(lines))


def _resume_other(mgr, arg, render):
    """Continue a *different* session's stranded goal in this session's seat.

    Deliberately explicit rather than automatic: adopting someone else's goal
    changes what this session is for, so the user names it.
    """
    from atlas.engine.goal_loop import resume_prompt, scan_resumable_goals

    session_id = arg.strip()
    if not session_id:
        return GoalCommandResult(
            render("gateway.goal.resume_other_usage",
                   "Usage: /goal resume-other <session_id> (see /goal stranded)"), error=True)
    home = getattr(mgr, "home", None)
    match = next(
        (g for g in scan_resumable_goals(home) if g.session_id == session_id), None)
    if match is None:
        return GoalCommandResult(
            render("gateway.goal.resume_other_missing",
                   "No stranded goal for session {session}. Run /goal stranded.",
                   session=session_id), error=True)
    if match.session_id == mgr.session_id:
        # This session already owns it, so it is not stranded here — the goal is
        # exactly what this seat is working on. Re-adopting would reset its
        # turn budget and its subgoal completions.
        return GoalCommandResult(
            render("gateway.goal.resume_other_own",
                   "Session {session} is this session; its goal is already the active one. "
                   "Use /goal status.", session=session_id), error=True)
    # Adopt the goal text so this session owns it; the foreign row stays as it
    # was, because archiving another session's record is not this command's job.
    state = mgr.set(match.goal)
    return GoalCommandResult(
        render("gateway.goal.resume_other_ok",
               "▶ Adopted goal from session {session} ({budget}-turn budget): {goal}",
               session=session_id, budget=state.max_turns, goal=state.goal),
        prompt=resume_prompt(match), kickoff=True)


_GATE_HANDLERS = {"add": _gate_add, "remove": _gate_remove, "rm": _gate_remove, "clear": _gate_clear}
_EXACT_HANDLERS = {
    "": _status, "status": _status, "show": _show, "pause": _pause,
    "resume": _resume, "continue": _resume, "unpause": _resume,
    "clear": _clear, "stop": _clear, "done": _clear, "unwait": _unwait,
}
# Non-destructive control verbs: with trailing words the verb still wins, so
# `/goal resume last goal` resumes instead of silently replacing the goal text.
# clear/stop/done stay out — guessing wrong would end a goal the user meant to keep.
_BARE_CONTROL_VERBS = frozenset({"resume", "continue", "unpause", "pause", "status", "show", "unwait"})
# First words that make a command goal control (the gateway busy path dispatches these).
_CONTROL_FIRST_WORDS = _BARE_CONTROL_VERBS | {"wait", "gate"}
_CONTROL_FIRST_WORDS = _CONTROL_FIRST_WORDS | {"subgoal", "stranded", "resume-other"}


def _bare_control(mgr, verb, rest, render):
    result = _EXACT_HANDLERS[verb](mgr, "", render)
    return replace(result, output=result.output + (
        f"\n(ignored {rest!r}: a control command never sets goal text — use /goal -- <text> "
        "when the goal really starts with a control word.)"))


def _gate(mgr, arg, authorize_gate):
    if not arg or arg.lower() == "list":
        return GoalCommandResult(mgr.render_gates())
    tokens = arg.split(None, 1)
    verb, rest = tokens[0].lower(), tokens[1].strip() if len(tokens) > 1 else ""
    handler = _GATE_HANDLERS.get(verb)
    if handler is None or (verb == "clear" and rest) or (verb != "clear" and not rest):
        return GoalCommandResult("Usage: /goal gate [list | add <command> | remove <N> | clear]", error=True)
    # Gates run shell commands without a later approval. The adapter must explicitly
    # authorize creation; recovery commands remain available to non-admin senders.
    if verb == "add" and (denial := authorize_gate()):
        return GoalCommandResult(denial, error=True)
    try:
        return handler(mgr, rest)
    except (RuntimeError, ValueError, IndexError) as exc:
        operation = "remove" if verb == "rm" else verb
        return GoalCommandResult(f"/goal gate {operation}: {exc}", error=True)


def _set(mgr, arg, *, drafting, last_user_message, render, progress):
    if drafting:
        if not arg:
            return GoalCommandResult("Usage: /goal draft <objective in plain language>", error=True)
        if progress is not None:
            progress("Drafting completion contract…")
        try:
            contract = goals.draft_contract(arg)
        except Exception as exc:
            logger.debug("goal draft failed: %s", exc)
            contract = None
        headline = arg
    else:
        headline, contract = goals.parse_contract(arg)
        contract = contract if not contract.is_empty() else None
    previous = mgr.state.goal if mgr.has_goal() else ""
    state = mgr.set(headline or arg, contract=contract)
    output = render("gateway.goal.set", "⊙ Goal set ({budget}-turn budget): {goal}",
                    budget=state.max_turns, goal=state.goal)
    if previous and previous != state.goal:
        output += f"\n(replaced the previous goal)\n  was: {previous}"
    if state.has_contract():
        label = "Drafted completion contract:" if drafting else "Completion contract:"
        output += f"\n{label}\n{state.contract.render_block()}"
    if drafting:
        output += ("\nTighten any field by re-setting the goal with inline lines "
                   "(e.g. verify: <command>), then /goal resume. Use /goal show to review."
                   if state.has_contract() else
                   "\nCouldn't draft a contract (aux model unavailable) — running as a "
                   "free-form goal. The per-turn judge still applies.")
    else:
        against = " against the contract above" if state.has_contract() else ""
        output += (f"\nAfter each turn, a judge model checks if the goal is done{against}. "
                   "Atlas keeps working until it is, you pause/clear it, or the budget is "
                   "exhausted. Use /goal status, /goal show, /goal pause, /goal resume, /goal clear.")
    return GoalCommandResult(output, goals.goal_kick_prompt(state.goal, last_user_message), kickoff=True)


def is_goal_control(arg: str) -> bool:
    """Whether this command controls an existing goal rather than replacing it."""
    normalized = arg.strip().lower()
    first = normalized.split(None, 1)[0] if normalized else ""
    return normalized in _EXACT_HANDLERS or first in _CONTROL_FIRST_WORDS


def dispatch_goal_command(
    mgr: goals.GoalManager, arg: str, *, authorize_gate: Callable[[], str | None],
    last_user_message=None, render: Callable = _english,
    progress: Callable[[str], None] | None = None,
) -> GoalCommandResult:
    """Apply one command. ``authorize_gate`` returns a denial or None (explicit approval).

    Synchronous like GoalManager: async adapters run this off-loop with copied
    ContextVars so draft credentials and persisted I/O stay in the caller's profile.
    """
    arg = arg.strip()
    tokens = arg.split(None, 1)
    verb = tokens[0].lower() if tokens else ""
    rest = tokens[1].strip() if len(tokens) > 1 else ""
    prefix = "Invalid goal"
    try:
        if verb == "--":
            # Verbatim goal text for goals that start with a control word (`/goal -- pause the cron`).
            return _set(mgr, rest, drafting=False, last_user_message=last_user_message,
                        render=render, progress=progress)
        if handler := _EXACT_HANDLERS.get(arg.lower()):
            return handler(mgr, "", render)
        if verb in _BARE_CONTROL_VERBS:
            return _bare_control(mgr, verb, rest, render)
        if verb == "wait":
            prefix = "/goal wait"
            return _wait(mgr, rest)
        if verb == "gate":
            prefix = "/goal gate"
            return _gate(mgr, rest, authorize_gate)
        if verb == "subgoal":
            prefix = "/goal subgoal"
            return _subgoal(mgr, rest)
        if verb == "plan":
            prefix = "/goal plan"
            return _plan(mgr, rest)
        if verb == "stranded":
            prefix = "/goal stranded"
            return _stranded(mgr, rest, render)
        if verb == "resume-other":
            prefix = "/goal resume-other"
            return _resume_other(mgr, rest, render)
        return _set(mgr, rest if verb == "draft" else arg,
                    drafting=verb == "draft", last_user_message=last_user_message,
                    render=render, progress=progress)
    except (RuntimeError, ValueError, IndexError) as exc:
        output = (render("gateway.goal.invalid", "Invalid goal: {error}", error=str(exc))
                  if prefix == "Invalid goal" else f"{prefix}: {exc}")
        return GoalCommandResult(output, error=True)

