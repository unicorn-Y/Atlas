import os
from pathlib import Path
import tempfile

import pytest

# Collection imports application modules before fixtures run. Never let those
# imports resolve settings, MCP clients or log/state files in the operator's home.
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="atlas-tests-"))
for _key, _folder in {
    "HOME": "home", "USERPROFILE": "home", "APPDATA": "home/appdata",
    "LOCALAPPDATA": "home/localappdata", "HERMES_HOME": "hermes",
    "ATLAS_DATA_DIR": "atlas",
}.items():
    _path = _TEST_ROOT / _folder
    _path.mkdir(parents=True, exist_ok=True)
    os.environ[_key] = str(_path)
for _key in list(os.environ):
    if _key.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS")):
        os.environ.pop(_key, None)
os.environ["ATLAS_SCHEDULER_ENABLED"] = "false"
_config = _TEST_ROOT / "atlas/config/atlas.toml"
_config.parent.mkdir(parents=True, exist_ok=True)
_config.write_text('[agent]\nengine="hermes"\n[tools]\nauto_start=[]\n[tools.servers]\n', encoding="utf-8")

# What the Electron main process attaches to renderer requests (see atlas.origin_guard).
API_TOKEN = "test-atlas-api-token"


@pytest.fixture(autouse=True)
def _atlas_api_token(monkeypatch):
    monkeypatch.setenv("ATLAS_API_TOKEN", API_TOKEN)
