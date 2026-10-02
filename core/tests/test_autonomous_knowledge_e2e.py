"""End-to-end closure checks for the autonomous knowledge advisory loop."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from atlas.agent import AgentOrchestrator
from atlas.memory import MemoryStore




def _completion(value: str):
    return SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content=value)
    )])


def _stream(value: str):
    async def chunks():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content=value, tool_calls=None)
        )])
    return chunks()
