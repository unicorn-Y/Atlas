import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = 'https://www.sqlite.org/2026/sqlite-dll-win-x64-3540000.zip';
// Pinned from the official archive; no checksum is accepted from the network at build time.
const checksum = 'a548a9b5d8f695e669f71bcc4669fdc8b3e1eb79995761c81a9128262126f71c';
const dllChecksum = '5ca6a16bdd2c5a5037b1e3a942d9ac1c66efe2def902b202d44774680a8a4656';
const staging = path.join(frontend, 'backend-build', 'sqlite-runtime');
const target = path.join(frontend, 'backend-release', 'atlas_backend', '_internal', 'sqlite3.dll');
const verifyOnly = process.argv.includes('--verify-only');
if (process.argv.slice(2).some((arg) => arg !== '--verify-only')) throw new Error('Usage: package-sqlite.mjs [--verify-only]');
if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('SQLite runtime requires Windows x64.');
// Refuse junctions/symlinks in the destination chain, including an existing DLL.
for (const destination of [staging, target]) {
  for (let current = destination; current !== frontend; current = path.dirname(current)) {
    if (fs.lstatSync(current, { throwIfNoEntry: false })?.isSymbolicLink()) throw new Error(`Unsafe SQLite build path: ${current}`);
  }
}
if (!verifyOnly && !fs.existsSync(target)) throw new Error('Build the backend before replacing its bundled SQLite runtime.');
const localArchive = process.env.ATLAS_SQLITE_ARCHIVE?.trim();
let bytes;
if (localArchive) {
  bytes = fs.readFileSync(path.resolve(localArchive));
} else {
  const response = await fetch(source, { signal: AbortSignal.timeout(60_000) });
  if (!response.ok) throw new Error(`SQLite download failed: HTTP ${response.status}`);
  bytes = Buffer.from(await response.arrayBuffer());
}
const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');
if (sha256(bytes) !== checksum) throw new Error('SQLite archive SHA-256 mismatch.');
console.log(`SQLite archive SHA-256 verified: ${checksum}`);
fs.mkdirSync(staging, { recursive: true });
const archive = path.join(staging, 'sqlite.zip');
fs.writeFileSync(archive, bytes);
const quote = (value) => `'${value.replaceAll("'", "''")}'`;
const extracted = path.join(staging, 'extract');
fs.rmSync(extracted, { recursive: true, force: true });
const result = spawnSync('powershell.exe', ['-NoProfile', '-Command',
  `Expand-Archive -LiteralPath ${quote(archive)} -DestinationPath ${quote(extracted)} -Force`],
  { windowsHide: true, stdio: 'inherit' });
if (result.error) throw result.error;
if (result.status !== 0) throw new Error('SQLite archive extraction failed.');
const dll = path.join(extracted, 'sqlite3.dll');
if (sha256(fs.readFileSync(dll)) !== dllChecksum) throw new Error('SQLite DLL SHA-256 mismatch.');
// Loading by absolute path verifies this DLL without changing the interpreter's SQLite.
const venvPython = path.resolve(frontend, '..', 'core', '.venv', 'Scripts', 'python.exe');
const python = process.env.ATLAS_BUILD_PYTHON || (fs.existsSync(venvPython) ? venvPython : 'py');
const probe = spawnSync(python, [...(python === 'py' ? ['-3'] : []), '-B', '-c',
  'import ctypes,sys; d=ctypes.CDLL(sys.argv[1]); d.sqlite3_libversion.restype=ctypes.c_char_p; v=d.sqlite3_libversion().decode(); print("SQLite staged DLL version: " + v); import sqlite3; c=sqlite3.connect(":memory:"); c.execute("create table probe(value)"); c.execute("insert into probe values (1)"); ok=c.execute("pragma quick_check").fetchone()[0]; print("Python SQLite compatibility: " + sqlite3.sqlite_version + "; quick_check=" + ok); c.close(); sys.exit(0 if v == sqlite3.sqlite_version == "3.54.0" and ok == "ok" else 1)', dll],
  { windowsHide: true, stdio: 'inherit' });
if (probe.error) throw probe.error;
if (probe.status !== 0) throw new Error('SQLite staged DLL version probe failed.');
if (verifyOnly) {
  console.log(`Verified SQLite 3.54.0 DLL: ${dll}; no bundle or Python DLL replaced.`);
} else {
  fs.copyFileSync(dll, target);
  if (sha256(fs.readFileSync(target)) !== dllChecksum) throw new Error('Bundled SQLite DLL SHA-256 mismatch.');
  console.log(`Bundled SQLite updated to verified official 3.54.0: ${target}`);
}
