import { describe, expect, it, vi } from 'vitest';
import { hasFileDropPayload, isBlockedFileDropTarget, readDroppedItems } from './fileDrop';

describe('file drop routing', () => {
  it('recognizes native file payloads and ignores internal text drags', () => {
    expect(hasFileDropPayload({ types: ['Files'] } as unknown as DataTransfer)).toBe(true);
    expect(hasFileDropPayload({ types: ['text/plain'] } as unknown as DataTransfer)).toBe(false);
  });

  it('keeps drops on interactive controls and dedicated drag surfaces out of the window handler', () => {
    const closest = vi.fn((selector: string) => selector.includes('button') ? {} as Element : null);
    expect(isBlockedFileDropTarget({ closest } as unknown as EventTarget)).toBe(true);
    expect(isBlockedFileDropTarget({ closest: vi.fn(() => null) } as unknown as EventTarget)).toBe(false);
    expect(isBlockedFileDropTarget(null)).toBe(false);
  });

  it('retains ordinary files from a DataTransfer payload', async () => {
    const file = new File(['hello'], 'note.txt', { type: 'text/plain' });
    const transfer = {
      items: [{ webkitGetAsEntry: () => null, getAsFile: () => file }],
      files: [file],
    } as unknown as DataTransfer;
    await expect(readDroppedItems(transfer)).resolves.toEqual({ files: [file], folders: [] });
  });
});
