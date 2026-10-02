from __future__ import annotations

import copy

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from atlas.agent import AgentOrchestrator, AgentRunContext, SYSTEM_PROMPT
from atlas.agent.prompt_caching import strip_anthropic_cache_control


class _ModelManager:
    current_model = "claude-sonnet-4"
    current_litellm_model = "anthropic/claude-sonnet-4"
    gateway_base_url = "https://api.anthropic.com/v1"

    def list_models(self):
        return [{
            "id": self.current_model,
            "provider": "anthropic",
            "litellm_model": self.current_litellm_model,
        }]
