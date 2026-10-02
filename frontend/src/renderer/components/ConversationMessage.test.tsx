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

  it('renders a still-streaming reply as plain text that keeps newlines, then full markdown once settled', () => {
    const content = 'Hello **there**\n第二行';
    const streaming = renderToStaticMarkup(<ConversationMessage role="assistant" content={content} username="User" streaming />);
    // 流式中不做 Markdown 解析（省掉每个 delta 的重复解析），但保留换行和消息结构。
    expect(streaming).toContain('data-message-role="assistant"');
    expect(streaming).toContain('whitespace-pre-wrap');
    expect(streaming).toContain('Hello **there**');
    expect(streaming).toContain('第二行');
    expect(streaming).not.toContain('<strong>');

    const settled = renderToStaticMarkup(<ConversationMessage role="assistant" content={content} username="User" />);
    expect(settled).toContain('<strong>there</strong>');
  });

  it('is memoized and keeps identical output for identical props', () => {
    expect((ConversationMessage as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for('react.memo'));
    const render = () => renderToStaticMarkup(<ConversationMessage role="assistant" content={'# 标题\n\n正文'} username="User" />);
    expect(render()).toBe(render());
    expect(render()).toContain('<h1>标题</h1>');
  });
});
