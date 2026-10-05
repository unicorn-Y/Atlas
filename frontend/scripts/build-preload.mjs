import { build } from 'esbuild';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

await build({
  entryPoints: [path.join(frontendRoot, 'src/preload/index.cts')],
  outfile: path.join(frontendRoot, 'dist-electron/preload/index.cjs'),
  bundle: true,
  platform: 'node',
  format: 'cjs',
  external: ['electron'],
});
