import subprocess
import sys
import hashlib
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    expected = Path(__file__).parent / "fixture/tests/test_ttl_cache.py"
    actual = root / "tests/test_ttl_cache.py"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(expected.read_bytes()).digest():
        print("The original TTL cache tests were changed or removed.", file=sys.stderr)
        return 1
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30,
    )
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
