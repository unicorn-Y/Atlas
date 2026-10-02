import hashlib
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from feature_test_quality_t1 import validate_added_feature_tests


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    original = Path(__file__).parent / "fixture/tests/test_notes.py"
    actual = root / "tests/test_notes.py"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        print("The original note tests were changed or removed.", file=sys.stderr)
        return 1
    try:
        validate_added_feature_tests(Path(__file__).parent, root, "test_tag_search.py", "test_notes.py",
                                     ("TypeError: NoteService.create() takes", "AttributeError: 'Note' object has no attribute 'tags'"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    behavior = '''from src.service import NoteService
from src.store import NoteStore
s = NoteService(NoteStore())
a = s.create("a", "a", "", ["Work", "Home"])
b = s.create("b", "b", "", ["work"])
s.create("c", "c", "", [])
assert s.search_tags(["WORK", "home"]) == [a]
assert s.search_tags(["work", "home"], "any") == [a, b]
assert s.search_tags([]) == []
try:
    s.search_tags(["work"], "bad")
except ValueError:
    pass
else:
    raise AssertionError("bad mode accepted")
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
