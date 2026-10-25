import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FormattedMessageContent } from './ConversationMessage';

describe('FormattedMessageContent', () => {
  it('formats preview text with the conversation Markdown renderer', () => {
    const html = renderToStaticMarkup(<FormattedMessageContent content={'## 最近进展\n\n- 修复 **实时卡片**\n- [详情](https://example.com)'} />);
    expect(html).toContain('<h2>最近进展</h2>');
    expect(html).toContain('<strong>实时卡片</strong>');
    expect(html).toContain('href="https://example.com/"');
  });
});
