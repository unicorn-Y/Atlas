import pytest

# What the Electron main process attaches to renderer requests (see atlas.origin_guard).
API_TOKEN = "test-atlas-api-token"


@pytest.fixture(autouse=True)
def _atlas_api_token(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)
