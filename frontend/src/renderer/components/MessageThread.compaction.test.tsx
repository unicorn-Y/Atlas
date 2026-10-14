import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { ConversationMessage } from '@atlas/backend-adapter';
import { CompactionNotice } from './MessageThread';

describe('CompactionNotice', () => {
  it('renders a single collapsed separator with the persisted token counts', () => {
    const message: ConversationMessage = {
      id: 'summary-1', conversation_id: 'c1', role: 'user',
      content: '[Conversation continuation summary]\nKeep the agreed plan.\n[Preserved task state]\n- tests pending',
      metadata: { _compressed_summary: true, compaction_before_tokens: 12000, compaction_after_tokens: 4200 },
    };
    const html = renderToStaticMarkup(<CompactionNotice message={message} />);
    expect(html).toContain('已压缩上下文（12,000→4,200 token）');
    expect(html).not.toContain('Keep the agreed plan.');
    expect(html).not.toContain('data-message-role="user"');
  });
});
