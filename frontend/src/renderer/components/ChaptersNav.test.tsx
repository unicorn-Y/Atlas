import { describe, expect, it } from 'vitest';
import { createRef } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ConversationMessage } from '@atlas/backend-adapter';
import ChaptersNav from './ChaptersNav';

describe('ChaptersNav', () => {
  it('builds an automatic table of contents from assistant Markdown headings', () => {
    const history = [{ id: 'answer-1', role: 'assistant', content: '# Summary\n\n## Risks\n\n### Follow up' }] as ConversationMessage[];
    const html = renderToStaticMarkup(<ChaptersNav conversationId="c1" threadRef={createRef<HTMLDivElement>()} history={history} events={[]} />);
    expect(html).toContain('自动目录：Summary');
    expect(html).toContain('自动目录：Risks');
    expect(html).toContain('自动目录：Follow up');
    expect(html).toContain('aria-label="对话章节目录"');
  });
});
