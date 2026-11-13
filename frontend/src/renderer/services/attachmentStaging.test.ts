import { describe, expect, it, vi } from 'vitest';
import { contentAddressedId, readFileBytes } from './attachmentStaging';

describe('attachment staging primitives', () => {
  it('uses a stable SHA-256 content address', async () => {
    const bytes = new TextEncoder().encode('attachment');
    expect(await contentAddressedId(bytes)).toBe('sha256:602a5e69c3021bdbd3d25156a02d2cbb467605b8203248eea6af3fb42168d663');
    expect(await contentAddressedId(bytes)).toBe(await contentAddressedId(bytes));
  });

  it('reports progress and aborts an active read', async () => {
    const controller = new AbortController();
    const onProgress = vi.fn();
    const file = new Blob([new Uint8Array(64 * 1024)]);
    const pending = readFileBytes(file, controller.signal, (loaded, total) => onProgress(loaded, total));
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(onProgress).toHaveBeenCalled();
  });
});
