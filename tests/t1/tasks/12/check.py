import json
from pathlib import Path
import sys


def main():
    root = Path(sys.argv[1])
    source = root / "inputs/artifacts.json"
    assert source.read_bytes() == (Path(__file__).parent / "fixture/inputs/artifacts.json").read_bytes(), "input changed"
    artifacts = [name for name in json.loads(source.read_text(encoding="utf-8")) if name != "private.env"]
    answer = json.loads((root / "release.json").read_text(encoding="utf-8"))
    assert answer == {"release_id": "ATLAS-早期-731", "locale": "zh-HK", "artifacts": artifacts, "checksum_policy": "sha256"}, "early constraint lost"
    print("early compaction constraints: PASS")


if __name__ == "__main__":
    main()
