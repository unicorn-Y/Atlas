import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import Composer, { ComposerDraftMentions } from './Composer';
import { TooltipProvider } from '../ui/Tooltip';
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

  it('renders restored text, semantic context and staged file metadata together in the composer', () => {
    const draft: ComposerDraft = {
      text: 'Review the attached design', mentions: [{ kind: 'conversation', id: 'design-session', label: 'Design discussion' }],
      attachments: [{ id: `sha256:${'a'.repeat(64)}`, name: 'design.pdf', mime: 'application/pdf', size: 1024, kind: 'file' }],
    };
    const persisted = new Map<string, string>();
    writeComposerDraft({ setItem: (key, value) => { persisted.set(key, value); }, removeItem: (key) => { persisted.delete(key); } }, 'session-1', draft);
    const restored = readComposerDraft({ getItem: (key) => persisted.get(key) ?? null }, 'session-1');
    // The real app mounts Composer inside App's TooltipProvider; the static render needs the same Radix root.
    const markup = renderToStaticMarkup(<TooltipProvider><Composer value={restored.text} mentions={restored.mentions} files={restored.attachments} attachments={[]}
      onChange={vi.fn()} onSubmit={vi.fn()} placeholder="Message" onRemoveAttachment={vi.fn()} onPickImages={vi.fn()}
      listening={false} onToggleMic={vi.fn()} models={[]} model="test" onSelectModel={vi.fn()} onManageModels={vi.fn()} status="" /></TooltipProvider>);
    expect(markup).toContain('Review the attached design');
    expect(markup).toContain('Design discussion');
    expect(markup).toContain('design.pdf');
    expect(markup).toContain('1 KB');
  });
});
