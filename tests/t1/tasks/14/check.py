import importlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

assert_fixture_bytes(root, task, "requirements.json")
spec = json.loads((root / "requirements.json").read_text(encoding="utf-8"))
profile = importlib.import_module("src.profile")
catalog = importlib.import_module("src.catalog")
invoice = importlib.import_module("src.invoice")
assert profile.normalize_name(spec["people"][0]) == "Ada Lovelace"
assert [p["id"] for p in catalog.available(spec["products"], "zh-HK")] == ["p1"]
assert invoice.total_cents(spec["lines"]) == 1299
for name in ("test_profile.py", "test_catalog.py", "test_invoice.py"):
    path = root / "tests" / name
    assert path.is_file() and "assert " in path.read_text(encoding="utf-8"), f"missing independent test: {name}"
legacy = root / "tests" / "test_legacy.py"
assert legacy.read_bytes() == (task / "fixture" / "tests" / "test_legacy.py").read_bytes(), "legacy test changed"
print("three independent subgoals and tests: PASS")
