import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const outputs = [
  'dist',
  'dist-electron',
  'out',
  'windows-release',
  'backend-release',
  'backend-build',
];

for (const name of outputs) {
  const target = path.resolve(frontendRoot, name);
  if (path.dirname(target) !== frontendRoot) {
    throw new Error(`Refusing to clean a path outside the frontend directory: ${target}`);
  }
  console.log(`Cleaning release output: ${target}`);
  fs.rmSync(target, { recursive: true, force: true, maxRetries: 5, retryDelay: 500 });
}
