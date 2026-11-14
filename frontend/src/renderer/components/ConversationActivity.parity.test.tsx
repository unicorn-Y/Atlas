import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import ConversationActivity, { PendingApprovalDock, pendingApprovalEvents, RunChangesSummary, TimelineRow, type TimelineRowContext } from './ConversationActivity';

const event = (id: string, type: AgentEvent['type'], data: AgentEvent['data']): AgentEvent => ({
  id, runId: 'run', type, data, timestamp: '2026-11-14T10:00:00Z', sequence: 1,
});

describe('turn summary and approval composer controls', () => {
  it('renders a compacted replay as one streamed assistant node through the production component', () => {
    const events = [event('input', 'run.started', { content: 'Say hello' }), event('delta-one', 'message.delta', { content: 'Hello ' }), event('delta-two', 'message.delta', { content: 'world' })];
    const store = { busy: true, paused: false } as unknown as TimelineRowContext['store'];
    const html = renderToStaticMarkup(<ConversationActivity events={events} store={store} username="User" setTab={vi.fn()} />);
    expect(html).toContain('Hello world');
    expect(html.match(/data-message-role="assistant"/g)).toHaveLength(1);
    expect(html).toContain('Say hello');
  });

  it('renders a visible per-turn changes summary with file and line counts', () => {
    const html = renderToStaticMarkup(<RunChangesSummary changes={{ files: 3, additions: 21, deletions: 8 }} onOpen={vi.fn()} />);
    expect(html).toContain('查看本回合文件改动摘要');
    expect(html).toContain('本回合改了 3 个文件');
    expect(html).toContain('+21');
    expect(html).toContain('−8');
    expect(html).toContain('basis-full');
  });

  it('renders each unresolved approval in the composer dock with its allowed choices', () => {
    const request = event('request', 'approval.required', { tool: 'local_shell', input: { command: 'git status' }, allow_always_available: true });
    const store = { getRun: () => ({ events: [request] }), respondToApproval: vi.fn() } as unknown as TimelineRowContext['store'];
    const html = renderToStaticMarkup(<PendingApprovalDock events={[request]} store={store} />);
    expect(html).toContain('aria-label="待处理审批"');
    expect(html).toContain('shrink-0');
    expect(html).toContain('允许一次');
    expect(html).toContain('始终允许');
    expect(html).toContain('拒绝并说明');
  });

  it('matches responses to an exact approval and keeps unrelated requests pending', () => {
    const first = event('first', 'approval.required', { tool: 'local_shell' });
    const second = event('second', 'approval.required', { tool: 'local_edit' });
    const response = event('answer', 'approval.responded', { event_id: first.id, choice: 'allow_once' });
    expect(pendingApprovalEvents([first, second, response])).toEqual([second]);
    const store = { getRun: () => ({ events: [first, response] }) } as unknown as TimelineRowContext['store'];
    expect(renderToStaticMarkup(<PendingApprovalDock events={[first, response]} store={store} />)).toBe('');
  });

  it('renders plan review goals, steps, verification and execution choices through the real registry', () => {
    const plan = event('plan', 'run.plan.proposed', {
      event_id: 'plan-decision',
      plan: { goal: 'Ship the report', subtasks: [{ id: 'one', title: 'Build report', verification: 'Read the generated report' }] },
    });
    const context = { events: [plan], store: { answers: {}, getRun: () => ({ status: 'waiting' }), approvePlan: vi.fn(), stopTask: vi.fn() }, username: 'User', setTab: vi.fn(), busy: false } as unknown as TimelineRowContext;
    const html = renderToStaticMarkup(<TimelineRow item={{ kind: 'plan', id: plan.id, event: plan }} context={context} firstInTurn last />);
    expect(html).toContain('Ship the report');
    expect(html).toContain('Build report');
    expect(html).toContain('Read the generated report');
    expect(html).toContain('按计划执行');
    expect(html).toContain('修改计划');
    expect(html).toContain('不执行');
  });
});
