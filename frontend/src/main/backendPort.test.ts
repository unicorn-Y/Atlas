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
});
