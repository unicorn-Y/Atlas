import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = 'https://www.sqlite.org/2026/sqlite-dll-win-x64-3540000.zip';
const checksum = 'f5fb500c73a3afd89976386bb8e4fdc8b5b65c052e187fb1ada1f5de034cd45b';
const staging = path.join(frontend, 'backend-build', 'sqlite-runtime');
const target = path.join(frontend, 'backend-release', 'atlas_backend', '_internal', 'sqlite3.dll');
if (process.platform !== 'win32' || process.arch !== 'x64') throw new Error('SQLite runtime requires Windows x64.');
if (!fs.existsSync(target)) throw new Error('Build the backend before replacing its bundled SQLite runtime.');
const response = await fetch(source, { signal: AbortSignal.timeout(60_000) });
if (!response.ok) throw new Error(`SQLite download failed: HTTP ${response.status}`);
const bytes = Buffer.from(await response.arrayBuffer());
if (crypto.createHash('sha3-256').update(bytes).digest('hex') !== checksum) throw new Error('SQLite archive checksum mismatch.');
fs.mkdirSync(staging, { recursive: true });
const archive = path.join(staging, 'sqlite.zip');
fs.writeFileSync(archive, bytes);
const quote = (value) => `'${value.replaceAll("'", "''")}'`;
const extracted = path.join(staging, 'extract');
const result = spawnSync('powershell.exe', ['-NoProfile', '-Command',
  `Expand-Archive -LiteralPath ${quote(archive)} -DestinationPath ${quote(extracted)} -Force`],
  { windowsHide: true, stdio: 'inherit' });
if (result.status !== 0) throw new Error('SQLite archive extraction failed.');
fs.copyFileSync(path.join(extracted, 'sqlite3.dll'), target);
console.log('Bundled SQLite updated to verified official 3.54.0 (WAL-reset fix included).');
