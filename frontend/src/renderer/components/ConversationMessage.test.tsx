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
    expect(html).toMatch(/<a\b[^>]*href="https:\/\/example\.com\/"[^>]*>Atlas<\/a>/);
    expect(html).toContain('rel="noopener noreferrer"');
    const unsafe = renderToStaticMarkup(<ConversationMessage role="assistant" username="User" content="[unsafe](javascript:alert(1))" />);
    expect(unsafe).not.toContain('href="javascript:');
    expect(html).toContain('class="hljs language-python"');
    expect(html).toContain('hljs-keyword');
  });

  it('renders a still-streaming reply as markdown, closing unfinished syntax, and math once settled', () => {
    const streaming = renderToStaticMarkup(<ConversationMessage role="assistant" content={'## 标题\n\nHello **there'} username="User" streaming />);
    // 流式中也走 Markdown（Streamdown 补全未闭合的 **），不再满屏 ## 和 **。
    expect(streaming).toContain('data-message-role="assistant"');
    expect(streaming).toContain('<h2>标题</h2>');
    expect(streaming).toContain('<strong>there</strong>');

    const settled = renderToStaticMarkup(<ConversationMessage role="assistant" content={'公式 $E=mc^2$ 和 1~2 天，路径 `./src/**/*`'} username="User" />);
    expect(settled).toContain('class="katex"');
    expect(settled).not.toContain('<del>');
    expect(settled).toContain('<code>./src/**/*</code>');
  });

  it('is memoized and keeps identical output for identical props', () => {
    expect((ConversationMessage as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
    const render = () => renderToStaticMarkup(<ConversationMessage role="assistant" content={'# 标题\n\n正文'} username="User" />);
    expect(render()).toBe(render());
    expect(render()).toContain('<h1>标题</h1>');
  });

  it('shows stored message timestamps only when the local preference is enabled', () => {
    const original = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
    Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: { getItem: (key: string) => key === 'atlas.preference.message-timestamps' ? 'true' : null } });
    try {
      const html = renderToStaticMarkup(<ConversationMessage role="user" content="历史提问" username="User" createdAt="2026-10-25T14:30:00.000Z" />);
      expect(html).toContain('<time dateTime="2026-10-25T14:30:00.000Z"');
      expect(html).toContain('历史提问');
    } finally {
      if (original) Object.defineProperty(globalThis, 'localStorage', original);
      else delete (globalThis as { localStorage?: Storage }).localStorage;
    }
  });
});
