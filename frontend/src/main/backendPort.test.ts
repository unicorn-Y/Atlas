import { createServer } from 'node:net';
import { describe, expect, it } from 'vitest';
import { allocateBackendPort, injectBackendPort } from './backendPort.js';

describe('backend port assignment', () => {
  it('uses an OS-assigned loopback port and injects it before backend startup', async () => {
    const env: NodeJS.ProcessEnv = {};
    const port = await injectBackendPort(env);
    expect(port).toBeGreaterThan(0);
    expect(env.ATLAS_PORT).toBe(String(port));
  });

  it('preserves an explicit port and allocates distinct ports when no override is set', async () => {
    const fixed: NodeJS.ProcessEnv = { ATLAS_PORT: '8838' };
    await expect(injectBackendPort(fixed)).resolves.toBe(8838);
    const [first, second] = await Promise.all([allocateBackendPort(), allocateBackendPort()]);
    expect(first).not.toBe(second);
  });

  it('keeps only a usable explicit override and allocates for empty or invalid values', async () => {
    for (const invalid of ['', 'not-a-port', '0', '-1', '70000']) {
      const env: NodeJS.ProcessEnv = { ATLAS_PORT: invalid };
      const port = await injectBackendPort(env);
      expect(port).toBeGreaterThan(0);
      expect(port).toBeLessThanOrEqual(65535);
      expect(env.ATLAS_PORT).toBe(String(port));
      expect(env.ATLAS_PORT).not.toBe(invalid);
    }
  });

  it('releases the allocated port so the backend can bind the same loopback address', async () => {
    const port = await allocateBackendPort();
    const rebinding = createServer();
    await new Promise<void>((resolve, reject) => {
      rebinding.once('error', reject);
      rebinding.listen(port, '127.0.0.1', () => resolve());
    });
    await new Promise<void>((resolve) => rebinding.close(() => resolve()));
  });
});
