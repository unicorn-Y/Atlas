import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { ComposerDraftMentions } from './Composer';
import { readComposerDraft, writeComposerDraft, type ComposerDraft } from '../services/composerDraft';

describe('Composer draft restore UI', () => {
  it('restores a session mention chip from persisted draft data after a renderer reload', () => {
    const persisted = new Map<string, string>();
    const beforeReload = {
      getItem: (key: string) => persisted.get(key) ?? null,
      setItem: (key: string, value: string) => { persisted.set(key, value); },
      removeItem: (key: string) => { persisted.delete(key); },
    };
    const draft: ComposerDraft = {
      text: 'Review this change',
      mentions: [{ kind: 'file', id: 'src/main.ts', label: 'main.ts', hint: 'src/main.ts' }],
      attachments: [],
    };
    writeComposerDraft(beforeReload, 'conversation-1', draft);

    const afterReload = {
      getItem: (key: string) => persisted.get(key) ?? null,
    };
    const restored = readComposerDraft(afterReload, 'conversation-1');
    const markup = renderToStaticMarkup(<ComposerDraftMentions mentions={restored.mentions} />);

    expect(restored.text).toBe('Review this change');
    expect(markup).toContain('aria-label="引用的上下文"');
    expect(markup).toContain('main.ts');
  });
});
