import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(import.meta.url);
const electronRequire = createRequire(require.resolve('electron/package.json'));
const { downloadArtifact } = electronRequire('@electron/get');
const version = JSON.parse(fs.readFileSync(path.join(frontend, 'package.json'), 'utf8')).devDependencies.electron;
const target = path.join(frontend, 'electron-runtime');
const marker = path.join(target, 'version');
if (fs.existsSync(marker) && fs.readFileSync(marker, 'utf8').trim().replace(/^v/, '') === version) {
  console.log(`Verified staged Electron ${version}`);
  process.exit(0);
}
const archive = await downloadArtifact({ version, artifactName: 'electron', platform: 'win32', arch: 'x64' });
fs.mkdirSync(target, { recursive: true });
const quote = (value) => `'${value.replaceAll("'", "''")}'`;
const result = spawnSync('powershell.exe', ['-NoProfile', '-Command',
  `Expand-Archive -LiteralPath ${quote(archive)} -DestinationPath ${quote(target)} -Force`],
  { windowsHide: true, stdio: 'inherit' });
if (result.status !== 0 || fs.readFileSync(marker, 'utf8').trim().replace(/^v/, '') !== version) {
  throw new Error('Staged Electron version does not match the declared version.');
}
console.log(`Staged official Electron ${version} for release packaging.`);
