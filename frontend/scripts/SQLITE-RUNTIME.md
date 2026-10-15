# Windows SQLite runtime pin

`package:backend` runs `build-backend.mjs` (PyInstaller) and then
`package-sqlite.mjs`. The latter replaces only
`frontend/backend-release/atlas_backend/_internal/sqlite3.dll` before
electron-builder copies that directory to `resources/atlas/backend`.
`ATLAS_BUILD_PYTHON` selects the PyInstaller interpreter; otherwise the build
uses `core/.venv/Scripts/python.exe` and creates that venv when absent.
A venv normally loads SQLite from its base Python installation, so upgrading
Python packages alone does not upgrade that native library.

The pinned Windows x64 archive is SQLite **3.54.0**:

- Source: https://www.sqlite.org/2026/sqlite-dll-win-x64-3540000.zip
- Archive SHA-256: `a548a9b5d8f695e669f71bcc4669fdc8b3e1eb79995761c81a9128262126f71c`
- DLL SHA-256: `5ca6a16bdd2c5a5037b1e3a942d9ac1c66efe2def902b202d44774680a8a4656`
- Official archive SHA3-256, cross-checked when pinning:
  `f5fb500c73a3afd89976386bb8e4fdc8b5b65c052e187fb1ada1f5de034cd45b`

The hashes are committed constants. Build-time downloads cannot supply new
expected hashes. Both downloaded and offline archives must match the pin;
the extracted DLL must also match its pin and report exactly `3.54.0` through
`sqlite3_libversion()` before any bundle replacement.

Run just the download, extraction, hash checks and native version probe from
the repository root, without a backend build or DLL replacement:

```powershell
node frontend/scripts/package-sqlite.mjs --verify-only
```

For an offline archive, set `ATLAS_SQLITE_ARCHIVE` to its absolute ZIP path.
The version probe uses `ATLAS_BUILD_PYTHON`, the repository venv if present,
or the Windows `py -3` launcher. This requires an x64 Python interpreter.
After a backend build, `node frontend/scripts/package-sqlite.mjs` performs
the verified replacement in the fixed bundle location. The script rejects
destination symlinks/junctions and never accepts a Python installation as a
replacement target.

The WAL-reset fix boundary is documented at
https://www.sqlite.org/wal.html#walresetbug (3.51.3, or backports 3.50.7 /
3.44.6). The local official Codex source provides an analogous bundled-runtime
pin in `Codex-Official/03-SOURCE/codex-rs/Cargo.toml:408-410`, explicitly citing
that fix. Its Rust dependency choice is a reference for pinning the shipped
native runtime, rather than a Python DLL installation recipe.

This packaging change does not repair a running source checkout. The observed
`D:\Atlas\core\.venv` uses the shared Python314 installation and still reports
SQLite 3.50.4 with the WAL-reset vulnerability probe returning true. Updating
that shared installation requires separate user authorization and a coordinated
stop/backup/restart window. Full packaged backend startup and real channel
write/checkpoint validation remain release checks; the standalone probe does
not establish those results.
