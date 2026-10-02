import json
import os
from pathlib import Path
import sys


task = Path(__file__).parent
workspace = Path(sys.argv[1])
release_path = workspace / "release.json"
reference_path = task / "fixture" / "release.json"
if not release_path.is_file() or release_path.is_symlink():
    raise SystemExit("protected release.json is missing or replaced by a symlink")
if release_path.read_bytes() != reference_path.read_bytes():
    raise SystemExit("protected release.json was modified")

try:
    release = json.loads(release_path.read_text(encoding="utf-8"))
    recovery_path = workspace / "recovery.json"
    if not recovery_path.is_file() or recovery_path.is_symlink():
        raise ValueError("recovery.json is missing or is a symlink")
    recovery = json.loads(recovery_path.read_text(encoding="utf-8"))
except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
    raise SystemExit(f"invalid recovery artifact: {exc}") from exc

if not isinstance(release, dict) or not isinstance(recovery, dict):
    raise SystemExit("release and recovery artifacts must be JSON objects")
expected = {
    "incident_id": release.get("incident_id"),
    "recovered": True,
    "attempts": release.get("attempts"),
    "faults": release.get("faults"),
    "response": release.get("response"),
}
if recovery != expected:
    raise SystemExit("recovery.json does not accurately record the released incident and successful response")
evidence_path = os.environ.get("T1_FAULT_EVIDENCE_PATH")
if evidence_path:
    traces = json.loads(Path(evidence_path).read_text(encoding="utf-8"))
    if len(traces) != 1:
        raise SystemExit("expected one runner-owned provider trace")
    trace = traces[0]
    requests = trace.get("requests", [])
    if (trace.get("recovered") is not True or len(requests) < 4
            or [r.get("fault") for r in requests[:3]] != ["429", "500", "disconnect"]
            or not any(r.get("fault") is None and r.get("status") == 200
                       and r.get("completed") is True and not r.get("upstream_error")
                       and (not r.get("stream") or r.get("stream_done") is True) for r in requests[3:])):
        raise SystemExit("provider fault sequence and successful recovery were not observed")
print("provider recovery artifact and protected release input: PASS")
