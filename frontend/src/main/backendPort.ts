import { createServer } from 'node:net';

/** Select an unused loopback port before the backend or renderer starts. */
export async function allocateBackendPort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => resolve());
  });
  const address = server.address();
  if (!address || typeof address === 'string') {
    await new Promise<void>((resolve) => server.close(() => resolve()));
    throw new Error('操作系统没有返回可用的本地端口');
  }
  const port = address.port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

export async function injectBackendPort(env: NodeJS.ProcessEnv = process.env): Promise<number> {
  const configured = Number(env.ATLAS_PORT);
  if (env.ATLAS_PORT && Number.isInteger(configured) && configured > 0 && configured <= 65535) return configured;
  const port = await allocateBackendPort();
  env.ATLAS_PORT = String(port);
  return port;
}
