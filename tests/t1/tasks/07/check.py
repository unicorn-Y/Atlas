import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from feature_test_quality_t1 import validate_added_feature_tests


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    original = Path(__file__).parent / "fixture/tests/test_inventory.py"
    actual = root / "tests/test_inventory.py"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        print("The original inventory tests were changed or removed.", file=sys.stderr)
        return 1
    try:
        validate_added_feature_tests(Path(__file__).parent, root, "test_stock_adjustment.py", "test_inventory.py",
                                     ("AttributeError: 'InventoryService' object has no attribute 'adjust_stock'",))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    behavior = '''from src.service import InventoryService
from src.store import InventoryStore
s = InventoryService(InventoryStore())
s.add_product("A", "item", 4)
assert s.adjust_stock("A", 2).quantity == 6
assert s.adjust_stock("A", -1).quantity == 5
try:
    s.adjust_stock("A", -6)
except ValueError:
    pass
else:
    raise AssertionError("negative stock accepted")
assert s.get_product("A").quantity == 5
try:
    s.adjust_stock("missing", 1)
except KeyError:
    pass
else:
    raise AssertionError("unknown SKU accepted")
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
