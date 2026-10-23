"""Probe newline/encoding preservation and transactional multi-file rollback."""
from pathlib import Path
import tempfile

from atlas.kernel.edit import EditManager


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "legacy.txt"
        target.write_bytes("第一行\r\n第二行\r\n".encode("gbk"))
        manager = EditManager(root)
        manager.read_file("legacy.txt", encoding="gbk")
        result = manager.call_tool("edit", {
            "path": "legacy.txt", "old_string": "第二行", "new_string": "修改行",
        })
        assert not result["is_error"]
        raw = target.read_bytes()
        assert "修改行" in raw.decode("gbk") and b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")
        second = root / "second.txt"
        second.write_text("old\n", encoding="utf-8")
        manager.read_file("second.txt")
        before = raw
        patch = ("*** Begin Patch\n*** Update File: legacy.txt\n@@\n-修改行\n+已改\n"
                 "*** Update File: second.txt\n@@\n-old\n+new\n*** End Patch")
        original_write = manager._atomic_write

        def fail_second(path, content, previous):
            if path.name == "second.txt":
                raise OSError("fixture write failure")
            return original_write(path, content, previous)

        manager._atomic_write = fail_second
        failed = manager.call_tool("apply_patch", {"patch": patch})
        assert failed["is_error"] and "all files rolled back" in failed["data"]["error"]
        assert target.read_bytes() == before and second.read_text(encoding="utf-8") == "old\n"
    print("W2-8 encoding/newlines and multi-file rollback: PASS")


if __name__ == "__main__":
    main()
