"""Runner: force a specific Atlas source root before importing atlas.

Why: D:/Atlas/core/.venv/Lib/site-packages/_editable_impl_atlas_core.pth appends
D:/Atlas/core to sys.path, which shadows PYTHONPATH. Without this bootstrap the
harness silently imports the D:/Atlas baseline and reports baseline behaviour.

Usage: python run_verify.py <atlas_core_root>
"""
import os
import sys

root = sys.argv[1] if len(sys.argv) > 1 else r"D:\atlas-luna-w1-20261017\core"
root = os.path.abspath(root)

# Remove OTHER Atlas source roots (leaves site-packages and stdlib untouched).
def _is_atlas_src(p: str) -> bool:
    p = os.path.abspath(p or ".")
    base = os.path.basename(p).lower()
    return base == "core" and os.path.isdir(os.path.join(p, "atlas"))

sys.path[:] = [p for p in sys.path if not _is_atlas_src(p) or os.path.abspath(p) == root]
sys.path.insert(0, root)

import atlas  # noqa: E402
import atlas.kernel.model_call as mc  # noqa: E402

actual = os.path.abspath(mc.__file__)
if not actual.lower().startswith(root.lower()):
    print(f"FATAL: expected {root}, loaded {actual}")
    sys.exit(2)
print(f"[boot] atlas root = {root}")
print(f"[boot] model_call = {actual}")

sys.argv = [sys.argv[0]] + sys.argv[2:]
import runpy  # noqa: E402

runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_w1.py"),
               run_name="__main__")
