import { afterEach, describe, expect, it, vi } from 'vitest';
import { contentAddressedId, loadStagedAttachment, readFileBytes, stageAttachment } from './attachmentStaging';

function memoryIndexedDb(): IDBFactory {
  const rows = new Map<string, { id: string; blob: Blob }>();
  const database = {
    close: vi.fn(),
    createObjectStore: vi.fn(),
    transaction: () => {
      const tx: Record<string, unknown> = {
        objectStore: () => ({
          put: (value: { id: string; blob: Blob }) => {
            rows.set(value.id, value);
            queueMicrotask(() => (tx.oncomplete as (() => void) | undefined)?.());
          },
          get: (id: string) => {
            const request: Record<string, unknown> = { result: rows.get(id) };
            queueMicrotask(() => (request.onsuccess as (() => void) | undefined)?.());
            return request;
          },
        }),
      };
      return tx;
    },
  };
  return {
    open: () => {
      const request: Record<string, unknown> = { result: database };
      queueMicrotask(() => (request.onsuccess as (() => void) | undefined)?.());
      return request;
    },
  } as unknown as IDBFactory;
}

afterEach(() => vi.unstubAllGlobals());

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

  it('persists staged file bytes by content address and restores them for sending', async () => {
    vi.stubGlobal('indexedDB', memoryIndexedDb());
    const file = new File(['durable attachment'], 'notes.txt', { type: 'text/plain' });
    const staged = await stageAttachment(file, 'file', new AbortController().signal, () => undefined);
    const restored = await loadStagedAttachment(staged.id);

    expect(staged).toMatchObject({ id: expect.stringMatching(/^sha256:/), name: 'notes.txt', kind: 'file' });
    expect(await restored?.text()).toBe('durable attachment');
  });
});
