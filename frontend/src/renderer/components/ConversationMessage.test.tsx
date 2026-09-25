import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import ConversationMessage from './ConversationMessage';

describe('ConversationMessage', () => {
  it('renders historical and streaming assistant content with the same message structure', () => {
    const historical = renderToStaticMarkup(<ConversationMessage role="assistant" content="Hello **there**" status="历史消息" />);
    const streaming = renderToStaticMarkup(<ConversationMessage role="assistant" content="Hello **there**" status="实时输出" />);

    expect(historical.replace('历史消息', 'STATUS')).toBe(streaming.replace('实时输出', 'STATUS'));
    expect(historical).toContain('<strong>there</strong>');
    expect(historical).toContain('data-message-role="assistant"');
  });
});
