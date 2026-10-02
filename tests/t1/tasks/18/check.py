from pathlib import Path
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

for relative in ("project/README.md", "project/metrics.csv"):
    assert_fixture_bytes(root, task, relative)
report = (root / "report.md").read_text(encoding="utf-8")
for text in ("## 项目概况", "## 关键指标", "## 风险与依据", "Atlas Relay", "17", "2", "89.47%", "region=hk"):
    assert text in report, f"missing or incorrect required report fact: {text}"
print("Markdown report facts: PASS")
