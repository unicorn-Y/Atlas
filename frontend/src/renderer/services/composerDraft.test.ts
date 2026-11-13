import { describe, expect, it } from 'vitest';
import { readComposerDraft, writeComposerDraft, serializeMentionContext, type ComposerDraft } from './composerDraft';

describe('composer drafts', () => {
  it('round trips text and semantic chips in session-scoped storage', () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => { values.set(key, value); },
      removeItem: (key: string) => { values.delete(key); },
    };
    const draft: ComposerDraft = {
      text: 'Review this',
      mentions: [{ kind: 'file', id: 'src/main.ts', label: 'main.ts', hint: 'src/main.ts' }],
      attachments: [],
    };

    writeComposerDraft(storage, 'conversation-1', draft);

    expect(readComposerDraft(storage, 'conversation-1')).toEqual(draft);
    expect(readComposerDraft(storage, 'conversation-2')).toEqual({ text: '', mentions: [], attachments: [] });
  });

  it('includes every chip kind in the model-facing text', () => {
    expect(serializeMentionContext('Review this', [
      { kind: 'file', id: 'src/main.ts', label: 'main.ts' },
      { kind: 'conversation', id: 'conv-7', label: 'Design' },
      { kind: 'resource', id: 'server\nfile:///notes', label: 'Notes' },
      { kind: 'element', id: 'slide-1', label: 'Title' },
    ])).toBe('Review this\n\n引用上下文：\n- 文件 main.ts（src/main.ts）\n- 请用 read_session 读取会话 conv-7（Design）\n- MCP 资源 Notes（server\nfile:///notes）\n- 请根据 PPT 元素引用进行精确修改：Title（文件/定位：slide-1）');
  });
});
