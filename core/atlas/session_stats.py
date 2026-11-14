"""Read-only session timing projection over the durable run archive."""

from pathlib import Path

from atlas.run_replay import list_runs, load_run


def session_timing_stats(session_id: str, runs_dir: Path | None = None) -> dict[str, int]:
    """Sum recorded timing observations across all archived runs of one session."""
    stats = dict.fromkeys(
        ("turns", "steps", "llmMs", "toolMs", "ttftMs", "ttftSteps", "decodeMs", "decodeTokens"), 0,
    )
    for info in list_runs(limit=None, runs_dir=runs_dir):
        if info.session_id != session_id:
            continue
        run = load_run(info.id, runs_dir=runs_dir)
        steps = run.count("step_end")
        stats["steps"] += steps
        stats["turns"] += int(steps > 0)
        for call in run.model_calls:
            if call.phase != "post":
                continue
            duration = max(0, call.duration_ms or 0)
            stats["llmMs"] += duration
            if call.first_token_ms is not None:
                first_token = max(0, call.first_token_ms)
                stats["ttftMs"] += first_token
                stats["ttftSteps"] += 1
                if call.output_tokens is not None:
                    stats["decodeMs"] += max(0, duration - first_token)
                    stats["decodeTokens"] += max(0, call.output_tokens)
        stats["toolMs"] += sum(max(0, call.duration_ms or 0) for call in run.tool_calls)
    return stats
