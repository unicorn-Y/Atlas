"""Atlas - All-in-one AI Personal Assistant."""

import os
from pathlib import Path

# CPython's Windows SQLite DLL may lag behind the runtime shipped with Atlas.
# Add the verified, app-local DLL directory before importing sqlite3 anywhere
# in Atlas so the stdlib extension binds to the same fixed runtime as releases.
_sqlite_dll_handle = None
_sqlite_dll_directory = None
if os.name == "nt":
    _sqlite_runtime = Path(__file__).with_name("_vendor")
    _sqlite_dll = _sqlite_runtime / "sqlite3.dll"
    if _sqlite_dll.is_file():
        import ctypes

        _sqlite_dll_handle = ctypes.WinDLL(str(_sqlite_dll))
        _sqlite_dll_directory = os.add_dll_directory(str(_sqlite_runtime))

__version__ = "0.1.0"
