import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import ConversationTrajectory from './ConversationTrajectory';
import type { AgentEvent } from '../../types/runtime';

describe('ConversationTrajectory', () => {
  it('renders readable events in order with their details', () => {
    const events = [
      { id: '1', timestamp: '2026-11-14T10:00:00Z', event: 'tool.started', data: { name: 'read_file', arguments: 'README.md' } },
      { id: '2', timestamp: '2026-11-14T10:00:01Z', event: 'message.completed', data: { role: 'assistant', content: 'Finished.' } },
    ] as unknown as AgentEvent[];
    const html = renderToStaticMarkup(<ConversationTrajectory events={events} />);
    expect(html.indexOf('开始工具 · read_file')).toBeLessThan(html.indexOf('助手回复'));
    expect(html).toContain('README.md');
    expect(html).toContain('Finished.');
  });
});
