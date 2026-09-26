import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ConversationMessage from './ConversationMessage';

describe('ConversationMessage', () => {
  it('renders historical and streaming assistant content with the same message structure', () => {
    const historical = renderToStaticMarkup(<ConversationMessage role="assistant" content="Hello **there**" username="User" status="历史消息" />);
    const streaming = renderToStaticMarkup(<ConversationMessage role="assistant" content="Hello **there**" username="User" status="实时输出" />);

    expect(historical.replace('历史消息', 'STATUS')).toBe(streaming.replace('实时输出', 'STATUS'));
    expect(historical).toContain('<strong>there</strong>');
    expect(historical).toContain('data-message-role="assistant"');
  });

  it('renders GitHub Markdown, safe links, and syntax-highlighted fenced code', () => {
    const html = renderToStaticMarkup(<ConversationMessage role="assistant" username="User" content={'- first\n- second\n\n[Atlas](https://example.com)\n\n```python\ndef read_json(path):\n    return path\n```'} />);

    expect(html).toContain('<ul>');
    expect(html).toContain('<a href="https://example.com">Atlas</a>');
    expect(html).toContain('class="hljs language-python"');
    expect(html).toContain('hljs-keyword');
  });
});
