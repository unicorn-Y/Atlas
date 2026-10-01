import pytest

# What the Electron main process attaches to renderer requests (see atlas.origin_guard).
API_TOKEN = "test-atlas-api-token"


@pytest.fixture(autouse=True)
def _atlas_api_token(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)


@pytest.fixture
def legacy_agent_engine(monkeypatch):
    """Keep pre-C1 LangGraph integration tests on their explicitly named fallback."""
    from atlas import config

    load_user_settings = config.load_user_settings
    monkeypatch.setattr(
        config,
        "load_user_settings",
        lambda: {**load_user_settings(), "agent_engine": "legacy"},
    )
