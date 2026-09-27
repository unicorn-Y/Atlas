import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(frontendDir, '..');
const manifest = JSON.parse(fs.readFileSync(path.join(frontendDir, 'node-runtime.json'), 'utf8'));
const outputRoot = path.join(frontendDir, 'backend-release');
const workRoot = path.join(frontendDir, 'backend-build', 'node-runtime');
const archivePath = path.join(workRoot, manifest.archive);
const extractDir = path.join(workRoot, 'extract');
const targetDir = path.join(outputRoot, 'runtime', 'node');
const localArchive = process.env.ATLAS_NODE_ARCHIVE?.trim();

function inside(parent, child) {
  const relative = path.relative(parent, child);
  return relative !== '' && !relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative);
}

function run(command, args) {
  const result = spawnSync(command, args, { windowsHide: true, stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error(`${command} exited with code ${result.status}`);
}

if (process.platform !== 'win32' || process.arch !== 'x64') {
  throw new Error('The bundled Node runtime is built only on Windows x64.');
}
if (!inside(frontendDir, outputRoot) || !inside(frontendDir, workRoot) || !inside(frontendDir, targetDir)) {
  throw new Error('Unsafe Node runtime build path.');
}

let archive;
let sourceSelection;
if (localArchive) {
  const resolvedArchive = path.resolve(localArchive);
  if (!fs.statSync(resolvedArchive, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`ATLAS_NODE_ARCHIVE does not point to a file: ${resolvedArchive}`);
  }
  sourceSelection = `local archive ${resolvedArchive}`;
  archive = fs.readFileSync(resolvedArchive);
}

console.log(`Clearing Node runtime staging: ${targetDir}`);
fs.rmSync(targetDir, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
fs.rmSync(workRoot, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
fs.mkdirSync(workRoot, { recursive: true });

if (!localArchive) {
  sourceSelection = `official source ${manifest.source}`;
  console.log(`Node runtime source: ${sourceSelection}`);
  const response = await fetch(manifest.source, { signal: AbortSignal.timeout(120_000) });
  if (!response.ok) throw new Error(`Node download failed with HTTP ${response.status}`);
  archive = Buffer.from(await response.arrayBuffer());
}

const actualHash = crypto.createHash('sha256').update(archive).digest('hex');
console.log(`Node runtime source selection: ${sourceSelection}`);
console.log(`Node runtime archive SHA-256: ${actualHash}`);
if (actualHash !== manifest.sha256) {
  throw new Error(`Node archive SHA-256 mismatch: expected ${manifest.sha256}, got ${actualHash}`);
}
fs.writeFileSync(archivePath, archive);
fs.mkdirSync(extractDir, { recursive: true });
const quotedArchive = `'${archivePath.replaceAll("'", "''")}'`;
const quotedDestination = `'${extractDir.replaceAll("'", "''")}'`;
run('powershell.exe', ['-NoProfile', '-Command', `Expand-Archive -LiteralPath ${quotedArchive} -DestinationPath ${quotedDestination} -Force`]);

const extractedRoot = path.join(extractDir, `node-v${manifest.version}-win-x64`);
const npmRoot = path.join(extractedRoot, 'node_modules', 'npm');
for (const required of [path.join(extractedRoot, 'node.exe'), path.join(npmRoot, 'bin', 'npm-cli.js'), path.join(npmRoot, 'bin', 'npx-cli.js')]) {
  if (!fs.existsSync(required)) throw new Error(`Official Node archive is missing ${path.relative(extractedRoot, required)}`);
}
fs.mkdirSync(targetDir, { recursive: true });
fs.copyFileSync(path.join(extractedRoot, 'node.exe'), path.join(targetDir, 'node.exe'));
fs.cpSync(npmRoot, path.join(targetDir, 'npm'), { recursive: true });
fs.copyFileSync(path.join(frontendDir, 'node-runtime.json'), path.join(targetDir, 'node-runtime.json'));
for (const license of ['LICENSE', 'LICENSE.txt']) {
  const source = path.join(extractedRoot, license);
  if (fs.existsSync(source)) fs.copyFileSync(source, path.join(targetDir, license));
}

const node = path.join(targetDir, 'node.exe');
const version = spawnSync(node, ['--version'], { encoding: 'utf8', windowsHide: true });
if (version.status !== 0 || version.stdout.trim() !== `v${manifest.version}`) {
  throw new Error(`Bundled Node validation failed: ${version.stdout.trim()} ${version.stderr ?? ''}`);
}
for (const script of ['npm-cli.js', 'npx-cli.js']) {
  const cli = path.join(targetDir, 'npm', 'bin', script);
  const checked = spawnSync(node, [cli, '--version'], { encoding: 'utf8', windowsHide: true, timeout: 30_000 });
  if (checked.status !== 0) throw new Error(`Bundled ${script} validation failed: ${checked.stderr ?? ''}`);
}
console.log(`Bundled Node ${version.stdout.trim()} and npm/npx under ${path.relative(repoRoot, targetDir)}; verified ${sourceSelection}; archive SHA-256 ${actualHash}`);
