import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from upstream_checkout_a import prepare


if len(sys.argv) != 2:
    raise SystemExit("usage: setup.py WORKSPACE")
prepare(
    Path(sys.argv[1]), "hermes-agent",
    "https://github.com/NousResearch/hermes-agent.git",
    "9a71d5a8b59b37d1795ab7065fbbe3b647ba5249",
)
