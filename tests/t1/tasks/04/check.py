import shutil
import subprocess
import sys
import hashlib
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "fixtures"))
from typescript_tools import compiler


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    original = Path(__file__).parent / "fixture/tests/run.cjs"
    actual = root / "tests/run.cjs"
    if not actual.is_file() or hashlib.sha256(actual.read_bytes()).digest() != hashlib.sha256(original.read_bytes()).digest():
        print("The original TypeScript tests were changed or removed.", file=sys.stderr)
        return 1
    tsc, node = compiler(root), shutil.which("node")
    if tsc is None or node is None:
        print("A real TypeScript compiler (tsc) and Node.js are required.", file=sys.stderr)
        return 2
    result = subprocess.run([node, str(tsc), "-p", "tsconfig.json"], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=45)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    if result.returncode:
        return result.returncode
    result = subprocess.run([node, "tests/run.cjs"], cwd=root, text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=30)
    print(result.stdout, end="")
    print(result.stderr, end="", file=sys.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
