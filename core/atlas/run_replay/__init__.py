"""Read-only run-replay / diff toolkit for Atlas run event logs.

The Atlas kernel appends one JSON object per line to
``data/logs/runs/<YYYY-MM-DD>/<run_id>.jsonl`` (see :func:`atlas.logs.append_run_event`).
Nothing in Atlas reads those files back, which makes tuning guesswork.

This package is strictly **read-only**:

* files are opened with ``open(path, "r")`` only -- never written, renamed or deleted;
* no network access, no model calls, no imports of the HTTP layer;
* every accessor tolerates malformed input instead of raising.

Public API
----------
``list_runs(limit=50)``   newest-first inventory of run files (:class:`RunInfo`).
``load_run(target)``      stream one run into a :class:`Run` (bad lines counted, never raised).
``summarize(run)``        duration / token / error / stuck-loop report as a plain ``dict``.
``replay(run)``           chronological :class:`TimelineItem` list.
``diff(a, b)``            structured comparison of two runs.
``format_diff(diff)``     human-readable text rendering of :func:`diff`.
"""

from __future__ import annotations

from .diffing import diff, format_diff
from .loader import (
    RunNotFoundError,
    default_runs_dir,
    iter_run_files,
    list_runs,
    load_run,
)
from .models import ModelCall, Run, RunInfo, TimelineItem, ToolCall
from .summary import DEFAULT_LOOP_THRESHOLD, format_summary, summarize
from .timeline import replay

__all__ = [
    "DEFAULT_LOOP_THRESHOLD",
    "ModelCall",
    "Run",
    "RunInfo",
    "RunNotFoundError",
    "TimelineItem",
    "ToolCall",
    "default_runs_dir",
    "diff",
    "format_diff",
    "format_summary",
    "iter_run_files",
    "list_runs",
    "load_run",
    "replay",
    "summarize",
]
