import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontendDir = path.resolve(scriptDir, '..');
const repoRoot = path.resolve(frontendDir, '..');
const packageJson = JSON.parse(fs.readFileSync(path.join(frontendDir, 'package.json'), 'utf8'));
const nodeManifest = JSON.parse(fs.readFileSync(path.join(frontendDir, 'node-runtime.json'), 'utf8'));
const backendSource = fs.readFileSync(path.join(repoRoot, 'core', 'atlas', '__init__.py'), 'utf8');
const backendVersion = backendSource.match(/^__version__\s*=\s*["']([^"']+)["']/m)?.[1];
const releaseDir = path.join(frontendDir, 'windows-release');
const installerName = `Atlas-${packageJson.version}-Setup.exe`;
const installerPath = path.join(releaseDir, installerName);
const unpackedExecutable = path.join(releaseDir, 'win-unpacked', 'Atlas.exe');
const backendExecutable = path.join(
  releaseDir,
  'win-unpacked',
  'resources',
  'atlas',
  'backend',
  'atlas_backend.exe',
);

function sha256(filePath) {
  return crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex');
}

function gitCommit() {
  const result = spawnSync('git', ['rev-parse', 'HEAD'], {
    cwd: repoRoot,
    encoding: 'utf8',
    windowsHide: true,
  });
  if (result.status !== 0) throw new Error(`Unable to read Git commit: ${result.stderr}`);
  return result.stdout.trim();
}

for (const required of [installerPath, unpackedExecutable, backendExecutable]) {
  if (!fs.statSync(required, { throwIfNoEntry: false })?.isFile()) {
    throw new Error(`Release output is missing required artifact: ${required}`);
  }
}
if (!backendVersion) throw new Error('Unable to determine the Atlas backend version.');

const manifest = {
  schema_version: 1,
  app_version: packageJson.version,
  git_commit: gitCommit(),
  electron_version: packageJson.devDependencies.electron,
  backend_build: {
    version: backendVersion,
    executable_sha256: sha256(backendExecutable),
  },
  bundled_node: {
    version: nodeManifest.version,
    platform: nodeManifest.platform,
    source: nodeManifest.source,
    canonical_archive_sha256: nodeManifest.sha256,
  },
  installer: {
    file: installerName,
    sha256: sha256(installerPath),
  },
  unpacked_executable_sha256: sha256(unpackedExecutable),
  build: {
    time_utc: new Date().toISOString(),
    platform: process.platform,
    architecture: process.arch,
    node_version: process.version,
  },
};

const destination = path.join(releaseDir, 'release-manifest.json');
fs.writeFileSync(destination, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8');
console.log(`Release manifest written: ${destination}`);
console.log(`Installer SHA-256: ${manifest.installer.sha256}`);
