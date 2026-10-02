import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from upstream_checkout_a import cleanup


if len(sys.argv) != 2:
    raise SystemExit("usage: cleanup.py WORKSPACE")
cleanup(Path(sys.argv[1]), "opencode")
