import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

assert_fixture_bytes(root, task, "transactions.json")
rows = json.loads((root / "transactions.json").read_text(encoding="utf-8"))
included = [row for row in rows if row["status"] in {"paid", "pending"}]
result = json.loads((root / "summary.json").read_text(encoding="utf-8"))
assert result == {"included_ids": [row["id"] for row in included],
                  "total_cents": sum(row["cents"] for row in included),
                  "note": "已应用中途更新"}
assert type(result["total_cents"]) is int
print("post-steer result: PASS")
