import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

assert_fixture_bytes(root, task, "request.json")
request = json.loads((root / "request.json").read_text(encoding="utf-8"))
result = json.loads((root / "result.json").read_text(encoding="utf-8"))
expected = {"migration": "legacy_key_to_canonical_key", "approved": True,
            "records": [{"canonical_key": row["legacy_key"], "value": row["value"]} for row in request["records"]],
            "total": sum(row["value"] for row in request["records"])}
assert result == expected, "approval-gated migration output incorrect"
print("approval-gated result: PASS")
