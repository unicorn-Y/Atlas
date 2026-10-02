from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1])
task = Path(__file__).parent
sys.path.insert(0, str(task.parents[1]))
from fixtures.scenario_check import assert_fixture_bytes

source = "资料/输入.txt"
assert_fixture_bytes(root, task, source)
script = root / "process.ps1"
assert script.is_file() and "WriteAllText" in script.read_text(encoding="utf-8"), "PowerShell implementation missing"
output = root / "结果" / "处理结果.txt"
output.unlink(missing_ok=True)
completed = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                           cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
assert completed.returncode == 0, f"PowerShell script failed: {completed.stderr[-1000:]}"
expected = (task / "fixture" / source).read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
assert output.is_file(), f"Chinese output path missing; stdout={completed.stdout!r}; stderr={completed.stderr!r}; files={[p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()]}"
actual = output.read_bytes()
assert actual == expected, "output bytes, UTF-8 encoding, or CRLF line endings differ"
assert b"\xef\xbb\xbf" not in actual and b"\n" not in actual.replace(b"\r\n", b""), "BOM or bare LF found"
print("PowerShell Chinese path and CRLF: PASS")
