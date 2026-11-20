import { existsSync } from 'node:fs';
import path from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { createServer } from 'vite';

const [frontendRoot, portText, closePath, envDir] = process.argv.slice(2);
const port = Number(portText);
if (!frontendRoot || !Number.isInteger(port) || !closePath || !envDir) {
  throw new Error('usage: dsh-electron-vite-server.mjs <frontend-root> <port> <close-file> <env-dir>');
}

const server = await createServer({
  configFile: path.join(frontendRoot, 'vite.config.ts'),
  root: frontendRoot,
  envDir,
  server: { host: '127.0.0.1', port, strictPort: true },
});
await server.listen();
const localUrl = server.resolvedUrls?.local?.[0] ?? '';
console.log(JSON.stringify({ ready: true, url: localUrl }));
while (!existsSync(closePath)) await delay(100);
await server.close();
console.log(JSON.stringify({ closed: true }));
