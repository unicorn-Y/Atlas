"""Collection must isolate user state before importing application modules."""

import json
import os
from pathlib import Path
import subprocess
import sys


def test_conftest_replaces_inherited_state_roots_before_collection(tmp_path):
    inherited = tmp_path / "inherited"
    inherited.mkdir()
    env = dict(os.environ)
    keys = ("HOME", "USERPROFILE", "HERMES_HOME", "ATLAS_DATA_DIR", "APPDATA", "LOCALAPPDATA")
    env.update({key: str(inherited) for key in keys})
    code = (
        "import importlib.util,json,os; "
        f"s=importlib.util.spec_from_file_location('isolation_probe',{str(Path(__file__).with_name('conftest.py'))!r}); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        f"print(json.dumps({{k:os.environ[k] for k in {keys!r}}}))"
    )
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    roots = json.loads(result.stdout)
    assert all(Path(value).resolve() != inherited.resolve() for value in roots.values())
    assert all(Path(value).is_dir() for value in roots.values())
