import { spawn } from 'node:child_process';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const safetyModule = path.join(frontendDir, 'dist-electron', 'main', 'stdoutSafety.js');
const child = spawn(process.execPath, ['--input-type=module', '-e', `
  await import(${JSON.stringify(pathToFileURL(safetyModule).href)});
  process.stdout.write('READY\\n');
  setTimeout(() => {
    console.error('simulated log after stdout pipe closure');
    setTimeout(() => process.exit(0), 50);
  }, 100);
`], {
  cwd: frontendDir,
  env: { ...process.env, ATLAS_DATA_DIR: path.resolve(frontendDir, '..') },
  stdio: ['ignore', 'pipe', 'pipe'],
});
let childStderr = '';
child.stderr.setEncoding('utf8');
child.stderr.on('data', (chunk) => { childStderr += chunk; });

// Once the safety handlers are installed, closing both parent read ends simulates
// the launching command exiting and closing the child's stdout/stderr pipes.
await new Promise((resolve, reject) => {
  child.stdout.once('data', (chunk) => {
    if (chunk.toString().includes('READY')) resolve();
  });
  child.once('error', reject);
  child.once('exit', (code) => reject(new Error(`Child exited before READY with ${code}: ${childStderr}`)));
});
child.stdout.destroy();
child.stderr.destroy();
const exitCode = await new Promise((resolve, reject) => {
  child.once('error', reject);
  child.once('exit', (code) => resolve(code));
});

if (exitCode !== 0) {
  throw new Error(`Child exited with ${exitCode} after stdout was closed`);
}
console.log('Closed stdout pipe did not crash the main-process logger.');
