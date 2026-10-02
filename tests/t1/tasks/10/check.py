import hashlib
import subprocess
import sys
from pathlib import Path


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    task = Path(__file__).parent
    original = task / "fixture/tests/test_public_api.py"
    actual = root / "tests/test_public_api.py"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        print("The original public API tests were changed or removed.", file=sys.stderr)
        return 1
    new_test = root / "tests/test_refactor.py"
    if not new_test.is_file() or "test_render_user_preserves_public_format" not in new_test.read_text(encoding="utf-8"):
        print("Add a test for the new presentation API.", file=sys.stderr)
        return 1
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        return result.returncode
    residue = []
    for folder in (root / "src", root / "tests"):
        for path in folder.rglob("*.py"):
            if "_format_user" in path.read_text(encoding="utf-8"):
                residue.append(path.relative_to(root).as_posix())
    if residue:
        print("Old private symbol remains in: " + ", ".join(residue), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
