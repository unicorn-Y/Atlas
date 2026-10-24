import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import TaskOverviewPanel from './TaskOverviewPanel';
import type { AgentEvent } from '../../../types/runtime';

describe('TaskOverviewPanel', () => {
  it('collects a real run plan, source, generated artifact, and reply summary in one view', () => {
    const events: AgentEvent[] = [
      { id: 'plan', runId: 'run-1', sequence: 1, type: 'run.plan.updated', timestamp: '2026-10-24T12:00:00Z', data: { plan: { subtasks: [{ id: 'inspect', title: '检查入口', status: 'completed' }] } } },
      { id: 'source', runId: 'run-1', sequence: 2, type: 'tool.started', timestamp: '2026-10-24T12:00:01Z', data: { name: 'local_file', arguments: { path: 'src/main.py' } } },
      { id: 'artifact', runId: 'run-1', sequence: 3, type: 'artifact.updated', timestamp: '2026-10-24T12:00:02Z', data: { name: '检查报告', path: 'reports/check.md', summary: '列出检查结果' } },
    ];
    const html = renderToStaticMarkup(<TaskOverviewPanel events={events} artifacts={[]} messages={[{ id: 'm1', role: 'assistant', content: '已经完成入口检查。' } as never]} onTab={() => undefined} />);
    expect(html).toContain('检查入口');
    expect(html).toContain('src/main.py');
    expect(html).toContain('reports/check.md');
    expect(html).toContain('已经完成入口检查');
    expect(html).toContain('查看活动');
    expect(html).toContain('浏览文件');
  });
});
