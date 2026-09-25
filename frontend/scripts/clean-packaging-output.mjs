import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outputDirs = [
  '.verify-atlas-dist',
  '.verify-atlas-final',
  'dist',
  'dist-electron',
  'out',
  'windows-release',
];

for (const name of outputDirs) {
  const target = path.resolve(frontendRoot, name);
  if (path.dirname(target) !== frontendRoot) {
    throw new Error(`Refusing to clean a path outside the frontend directory: ${target}`);
  }
  fs.rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
}

const legacyOutput = path.resolve(frontendRoot, 'release');
try {
  fs.rmSync(legacyOutput, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
} catch (error) {
  if (error?.code !== 'EPERM' && error?.code !== 'EBUSY') throw error;
  console.warn(`Skipping locked legacy packaging output: ${legacyOutput}`);
}
