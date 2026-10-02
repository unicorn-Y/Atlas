import hashlib
import json
import subprocess
import sys
from pathlib import Path

COMMIT = "9a71d5a8b59b37d1795ab7065fbbe3b647ba5249"
SOURCE = "tools/mcp_tool_discovery.py"
EXPECTED = {
    "default_concurrency": 4,
    "config_key": "mcp.discovery_concurrency",
    "zero_means": "unlimited",
    "negative_falls_back_to": 4,
    "boolean_falls_back_to": 4,
    "config_load_error_falls_back_to": 4,
}
SNAPSHOT_SHA256 = "D26AE438E3ABDB08AA7704A912D20F69859934AC05BDF3831490E4B60BE1677C"


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    task = Path(__file__).parent
    snapshot = root / "source/snapshot" / SOURCE
    if not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256:
        print("Protected snapshot was changed or removed.", file=sys.stderr)
        return 1
    full_repo = root / "source/upstream/hermes-agent"
    if full_repo.exists():
        commit = subprocess.run(["git", "-C", str(full_repo), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if commit.returncode or commit.stdout.strip() != COMMIT:
            print("Hermes checkout is not the required pinned commit.", file=sys.stderr)
            return 1
        source = full_repo / SOURCE
    else:
        source = root / "source/snapshot" / SOURCE
        snapshot = task / "fixture/source/snapshot" / SOURCE
        if (not snapshot.is_file()
                or hashlib.sha256(snapshot.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256
                or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256):
            print("Pinned offline Hermes source snapshot is missing or altered.", file=sys.stderr)
            return 1
    if not source.is_file():
        print(f"Missing source file: {SOURCE}", file=sys.stderr)
        return 1
    if source.read_text(encoding="utf-8") != snapshot.read_text(encoding="utf-8"):
        print("Pinned source content was changed.", file=sys.stderr)
        return 1
    try:
        answer = json.loads((root / "answer.json").read_text(encoding="utf-8"))
        evidence = answer["evidence"]
        valid = (
            answer.get("repository") == "NousResearch/hermes-agent"
            and answer.get("commit") == COMMIT
            and answer.get("source_path") == SOURCE
            and answer.get("facts") == EXPECTED
            and isinstance(evidence, list)
            and any(item.get("path") == SOURCE and item.get("start_line", 9999) <= 28 and item.get("end_line", 0) >= 42 for item in evidence)
        )
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        print("answer.json is missing required source-backed Hermes facts.", file=sys.stderr)
        return 1
    lines = source.read_text(encoding="utf-8").splitlines()
    evidence_lines = "\n".join(lines[24:43])
    if "_DISCOVERY_CONNECT_CONCURRENCY = 4" not in evidence_lines or "raw < 0" not in evidence_lines or "return raw" not in evidence_lines:
        print("Cited Hermes source lines do not support the expected answer.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
