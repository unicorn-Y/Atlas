"""Fixtures for the unified-memory real dual-service tests (T00.2).

The harness spawns its own uvicorn subprocesses with fully explicit isolated
env; it never touches the in-process ``atlas.server.app`` that the shared
core/tests/conftest.py guard protects, so both can coexist.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from tests.unified_memory.harness import UMHarness


@pytest.fixture(scope="session")
def um() -> UMHarness:
    """Session-wide harness: lazily started, stopped after the session."""
    harness = UMHarness()
    harness.start()
    yield harness
    harness.stop()


@pytest.fixture
def um_fresh() -> Callable[[], UMHarness]:
    """Factory for function-scoped fresh instances (restart/bootstrap tests)."""
    made: list[UMHarness] = []

    def _factory(**kwargs: Any) -> UMHarness:
        harness = UMHarness(**kwargs)
        harness.start()
        made.append(harness)
        return harness

    yield _factory
    for harness in made:
        try:
            harness.stop()
        except Exception:
            pass
