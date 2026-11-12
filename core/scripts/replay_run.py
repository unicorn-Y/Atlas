"""Replay and diff Atlas run logs from the command line.

Thin launcher for ``python -m atlas.run_replay`` so the tool also works from a
shell whose ``sys.path`` does not already contain ``core``::

    python scripts\\replay_run.py list
    python scripts\\replay_run.py show <run-id-prefix>
    python scripts\\replay_run.py diff <run-a> <run-b>

The archive under ``data/logs/runs`` is only ever opened for reading; this
entry point writes nothing, touches no network and calls no model.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from atlas.run_replay.__main__ import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
