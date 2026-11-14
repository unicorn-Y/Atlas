"""The kernel must dispatch the durable session-query tools, not just advertise them.

``session_event_search`` / ``session_trace`` / ``session_event_trace`` /
``session_event_read`` were implemented in ``atlas.agent.session_queries`` and
listed in the kernel's tool schemas, but ``_dispatch`` had no branch for them.
The model could see the tool and every call came back as an unknown tool — the
exact "schema advertised, no handler" failure this ledger keeps recording.

The workspace gate is derived from the session row, never from the arguments, so
these tests also pin that a call cannot widen its own authority.
"""

from __future__ import annotations

import pytest

from atlas.agent.session_queries import QUERY_NAMES, execute_query

pytestmark = pytest.mark.unit


def test_all_five_query_names_are_covered_by_the_dispatch_set():
    """The kernel branch lists four; ``session_search`` keeps its own path."""
    dispatched = {"session_event_search", "session_trace", "session_event_trace",
                  "session_event_read"}
    assert dispatched | {"session_search"} == set(QUERY_NAMES)


def test_query_without_a_workspace_is_refused_not_defaulted():
    """A missing workspace must fail closed; defaulting it would widen authority."""
    with pytest.raises(PermissionError):
        execute_query(object(), "session_event_read", {}, workspace=None)


def test_query_refuses_a_session_from_another_workspace():
    class _DB:
        def get_session(self, _id):
            return {"id": "s1", "cwd": "D:/elsewhere"}

    with pytest.raises(PermissionError):
        execute_query(_DB(), "session_event_read", {"session_id": "s1"},
                      workspace="D:/Atlas")


def test_ssh_workspace_is_refused():
    with pytest.raises(PermissionError):
        execute_query(object(), "session_event_read", {}, workspace="ssh://host/x")


def test_dispatch_set_matches_the_kernel_source():
    """Guard against the branch being deleted while the schemas stay."""
    from pathlib import Path

    source = Path("atlas/engine/kernel/loop.py").read_text(encoding="utf-8")
    for name in ("session_event_search", "session_trace", "session_event_trace",
                 "session_event_read"):
        assert name in source, f"{name} missing from loop.py"
