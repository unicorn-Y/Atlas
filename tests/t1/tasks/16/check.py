import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

assert_fixture_bytes(root, task, "plan.json")
plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
decision = json.loads((root / "decision.json").read_text(encoding="utf-8"))
assert decision == {"selected": "B", "flag": plan["canonical_flag"], "value": plan["canonical_value"], "rewound_from": "A"}
assert (root / "choice_b.txt").read_text(encoding="utf-8").strip() == f"方案 B 已应用：{plan['canonical_flag']}={plan['canonical_value']}"
assert not (root / "choice_a.txt").exists(), "rewound A change remains"
assert plan["legacy_flag"] not in json.dumps(decision, ensure_ascii=False)
print("rewind to B with no A residue: PASS")
