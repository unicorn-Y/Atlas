"""Shared behavior for Atlas's explicit long-task mode."""

from __future__ import annotations

DAYBREAK_INSTRUCTIONS = """[Atlas Daybreak long-task mode]
Treat the user's request as an ongoing task and work through it until the requested outcome is complete. Keep a concise progress/checkpoint summary in the conversation when a task spans multiple stages. If execution is paused, interrupted, or a tool/model call fails, preserve the completed work and make the next action clear so the same conversation can be resumed. Wait for long-running work to finish instead of treating a pending operation as success. Notify the user with the final outcome and any remaining limitation when the task reaches a terminal state.
"""


def daybreak_prompt(message: str) -> str:
    """Add the long-task contract once, so retries do not recursively prefix it."""
    if message.startswith(DAYBREAK_INSTRUCTIONS):
        return message
    return f"{DAYBREAK_INSTRUCTIONS}\nUser task:\n{message}"

