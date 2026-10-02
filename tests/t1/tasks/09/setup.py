import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from upstream_checkout_a import prepare


if len(sys.argv) != 2:
    raise SystemExit("usage: setup.py WORKSPACE")
prepare(
    Path(sys.argv[1]), "opencode",
    "https://github.com/anomalyco/opencode.git",
    "1ddb0873aee50d209d1a8d7f91b89c5daf692d49",
)
