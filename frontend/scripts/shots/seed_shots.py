# Prepare an isolated data dir for C6 screenshots: atlas.toml (fake gateway + fake LSP),
# HERMES_HOME engine dir, and a git workspace with a committed baseline file.
# Run: core/.venv/Scripts/python.exe scripts/shots/seed_shots.py <data-dir> <workspace> <fake-base-url>
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(sys.argv[1]).resolve()
WORKSPACE = Path(sys.argv[2]).resolve()
FAKE_URL = sys.argv[3]
sys.path.insert(0, str(ROOT / "core"))

FAKE_LSP = ROOT / "core" / "tests" / "fakes" / "fake_lsp_server.py"
PY = sys.executable

config_dir = DATA_DIR / "config"
config_dir.mkdir(parents=True, exist_ok=True)
lsp_command = json.dumps([PY, str(FAKE_LSP), "--server-id", "fake", "--delay-ms", "50",
                          "--state-file", str(DATA_DIR / "fake_lsp_state.json")])
(config_dir / "atlas.toml").write_text(
    '[models]\ndefault="fake-model"\n'
    f'[models.gateway]\nbase_url="{FAKE_URL}"\napi_key="sk-fake-shots"\n'
    '[[models.custom]]\nid="fake-model"\nname="Fake 演示"\nprovider="openai"\nlitellm_model="openai/fake-model"\nmax_output_tokens=512\n'
    '[agent]\nengine="hermes"\nverify_before_stop=false\n'
    '[tools]\nauto_start=[]\n[tools.servers]\n'
    '[scheduler]\nenabled=false\n'
    '[lsp]\nenabled=true\nwait_timeout=25.0\n'
    'trusted_workspaces=[' + json.dumps(str(ROOT)) + ']\n'
    '[lsp.servers.fake]\ncommand=' + lsp_command + '\nextensions=[".py"]\n',
    encoding="utf-8",
)

from tests.fakes.fake_llm_provider import write_hermes_home  # noqa: E402

write_hermes_home(DATA_DIR / "engine", FAKE_URL,
                  extra_config="auxiliary:\n  title_generation:\n    model_upgrade_enabled: false\n")

if not (WORKSPACE / ".git").exists():
    subprocess.run(["git", "init", "-b", "main", str(WORKSPACE)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(WORKSPACE), "config", "user.email", "shots@example.invalid"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(WORKSPACE), "config", "user.name", "Shots"],
                   check=True, capture_output=True)
    (WORKSPACE / "README.md").write_text("# 演示工作区\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(WORKSPACE), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(WORKSPACE), "commit", "-m", "baseline"], check=True,
                   capture_output=True)
print("ready", flush=True)
