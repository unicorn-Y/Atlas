import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import ConversationTrajectory from './ConversationTrajectory';

describe('ConversationTrajectory', () => {
  it('renders a readable ordered alternate view of tool calls and results', () => {
    const events = [
      { id: 'start', type: 'tool.started', data: { tool_name: 'read_file', arguments: '{"path":"src/main.ts"}' } },
      { id: 'result', type: 'tool.completed', data: { tool_name: 'read_file', content: 'source contents' } },
    ].map((event, index) => ({ ...event, runId: 'run-1', sequence: index + 1, timestamp: `2026-11-14T12:00:0${index}Z` })) as AgentEvent[];
    const html = renderToStaticMarkup(<ConversationTrajectory events={events} />);
    expect(html).toContain('aria-label="会话轨迹"');
    expect(html).toContain('read_file');
    expect(html).toContain('src/main.ts');
    expect(html).toContain('source contents');
    expect(html.indexOf('#1')).toBeLessThan(html.indexOf('#2'));
    expect(html).not.toContain('[object Object]');
  });
});
