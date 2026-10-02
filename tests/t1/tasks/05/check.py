import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from feature_test_quality_t1 import validate_added_feature_tests


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    original = Path(__file__).parent / "fixture/tests/test_catalog.py"
    actual = root / "tests/test_catalog.py"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        print("The original catalog tests were changed or removed.", file=sys.stderr)
        return 1
    try:
        validate_added_feature_tests(Path(__file__).parent, root, "test_search.py", "test_catalog.py",
                                     ("AttributeError: 'Catalog' object has no attribute 'search_prefix'",))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    behavior = '''from src.catalog import Catalog
from src.item import Item
c = Catalog()
for item in [Item("z", "beta"), Item("b", "BETA"), Item("a", "Berry")]: c.add(item)
assert [x.id for x in c.search_prefix("Be")] == ["a", "b", "z"]
assert [x.id for x in c.search_prefix("", 1)] == ["a"]
assert c.search_prefix("b", 0) == []
try:
    c.search_prefix("b", -1)
except ValueError:
    pass
else:
    raise AssertionError("negative limit accepted")
'''
    direct = subprocess.run([sys.executable, "-"], input=behavior, cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=20)
    if direct.returncode:
        print(direct.stderr, end="", file=sys.stderr)
        return direct.returncode
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
