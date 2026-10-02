import hashlib
import json
import subprocess
import sys
from pathlib import Path

COMMIT = "1ddb0873aee50d209d1a8d7f91b89c5daf692d49"
SOURCE = "packages/opencode/src/provider/provider.ts"
EXPECTED = {
    "configured_small_model": "parse and getModel; missing model yields undefined",
    "plugin_precedes_provider_fallback": True,
    "azure_provider_fallback": "undefined",
    "opencode_family_priority": ["gpt-nano"],
    "github_copilot_family_priority": ["gpt-mini", "gemini-flash", "gpt-nano", "claude-haiku"],
    "other_family_priority": ["gemini-flash", "gpt-nano", "claude-haiku"],
    "candidate_sort": ["release_date:desc", "id:desc"],
    "bedrock_candidate_order": ["global-prefix", "configured-us-or-eu-region-prefix", "unprefixed"],
    "bedrock_region_prefix": "first segment of region; only us and eu are selected",
}
SNAPSHOT_SHA256 = "B5E04B63B7B39311EA37AB2108F1225812D11896C8647EFDF1E17EEDFB46BF87"


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    task = Path(__file__).parent
    snapshot = root / "source/snapshot" / SOURCE
    if not snapshot.is_file() or hashlib.sha256(snapshot.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256:
        print("Protected snapshot was changed or removed.", file=sys.stderr)
        return 1
    full_repo = root / "source/upstream/opencode"
    if full_repo.exists():
        commit = subprocess.run(["git", "-C", str(full_repo), "rev-parse", "HEAD"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        if commit.returncode or commit.stdout.strip() != COMMIT:
            print("OpenCode checkout is not the required pinned commit.", file=sys.stderr)
            return 1
        source = full_repo / SOURCE
    else:
        source = root / "source/snapshot" / SOURCE
        snapshot = task / "fixture/source/snapshot" / SOURCE
        if (not snapshot.is_file()
                or hashlib.sha256(snapshot.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256
                or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest().upper() != SNAPSHOT_SHA256):
            print("Pinned offline OpenCode source snapshot is missing or altered.", file=sys.stderr)
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
        ranges_ok = (
            isinstance(evidence, list)
            and any(item.get("path") == SOURCE and item.get("start_line", 9999) <= 1964 and item.get("end_line", 0) >= 2027 for item in evidence)
            and any(item.get("path") == SOURCE and item.get("start_line") == 2070 and item.get("end_line") == 2070 for item in evidence)
        )
        valid = answer.get("repository") == "anomalyco/opencode" and answer.get("commit") == COMMIT and answer.get("source_path") == SOURCE and answer.get("facts") == EXPECTED and ranges_ok
    except (OSError, ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        print("answer.json is missing required source-backed OpenCode facts.", file=sys.stderr)
        return 1
    lines = source.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2070 or "globalMatch" not in "\n".join(lines[2007:2022]) or 'const smallModelFamilyPriority = ["gemini-flash", "gpt-nano", "claude-haiku"]' not in lines[2069]:
        print("Cited OpenCode source lines do not support the expected answer.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
