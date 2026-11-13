import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import { buildTimeline, cacheShare, describeTool, duration, isPlanReviewIntent, shortPath, tokenCount } from './timeline';

let seq = 0;
const ev = (type: AgentEvent['type'], data: Record<string, unknown>, second = seq): AgentEvent =>
  ({ id: `e${++seq}`, runId: 'r1', sequence: seq, type, timestamp: new Date(Date.UTC(2026, 8, 29, 10, 0, second)).toISOString(), data });

describe('isPlanReviewIntent', () => {
  it('routes only explicitly tagged plan-review questions to the plan action', () => {
    expect(isPlanReviewIntent(ev('input.required', { intent: 'plan-review' }))).toBe(true);
    expect(isPlanReviewIntent(ev('input.required', { intent: 'clarification' }))).toBe(false);
    expect(isPlanReviewIntent(ev('input.required', { intent: 'plan-review', proposal: true }))).toBe(false);
  });
});

describe('describeTool', () => {
  it('turns Atlas local tools into plain-language steps', () => {
    expect(describeTool('local_file', { action: 'read', path: 'C:\\Users\\youdu\\Desktop\\Atlas\\README.md' })).toEqual({ verb: '读取', target: '…\\Atlas\\README.md' });
    expect(describeTool('local_file', { action: 'list', path: 'C:\\Atlas' })).toEqual({ verb: '查看目录', target: 'C:\\Atlas' });
    expect(describeTool('local_file', { action: 'search', path: 'src', query: 'TODO' })).toEqual({ verb: '搜索文件内容', target: 'TODO' });
    expect(describeTool('local_shell', { shell: 'powershell', command: 'Get-Date' })).toEqual({ verb: '运行命令', target: 'Get-Date' });
    expect(describeTool('local_exec', { executable: 'npm', args: ['run', 'build'] })).toEqual({ verb: '运行', target: 'npm run build' });
    expect(describeTool('local_git', { action: 'commit', repo: 'C:\\Users\\youdu\\Desktop\\Atlas' }).verb).toBe('提交改动');
  });

  it('falls back to keyword matching, then to the raw tool name', () => {
    expect(describeTool('browser_navigate', { url: 'https://example.com' })).toEqual({ verb: '打开网页', target: 'https://example.com' });
    expect(describeTool('mystery_tool', {})).toEqual({ verb: '使用工具', target: 'mystery_tool' });
  });
});

describe('buildTimeline', () => {
  it('pairs tool start and finish by tool_call_id and never shows bookkeeping events', () => {
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: '看看这个文件夹' }, 0),
      ev('run.status', { status: 'running' }, 0),
      ev('tool.started', { tool_call_id: 'a', name: 'local_file', arguments: { action: 'list', path: 'C:\\Atlas' } }, 1),
      ev('tool.started', { tool_call_id: 'b', name: 'local_file', arguments: { action: 'read', path: 'C:\\Atlas\\README.md' } }, 1),
      ev('tool.completed', { tool_call_id: 'a', name: 'local_file', result: 'ok' }, 2),
      ev('tool.completed', { tool_call_id: 'b', name: 'local_file', result: 'ok', is_error: true }, 4),
      ev('run.completed', {}, 5),
    ]);
    expect(items.map((item) => item.kind)).toEqual(['user', 'steps', 'done']);
    const steps = items[1].kind === 'steps' ? items[1].steps : [];
    expect(steps.map((step) => [step.verb, step.state])).toEqual([['查看目录', 'done'], ['读取', 'failed']]);
  });

  it('extracts the returned image for a read_file thumbnail', () => {
    seq = 0;
    const items = buildTimeline([
      ev('tool.started', { tool_call_id: 'image', name: 'read_file', arguments: { path: 'sample.png' } }),
      ev('tool.completed', {
        tool_call_id: 'image', name: 'read_file',
        result: JSON.stringify({ _multimodal: true, content: [
          { type: 'image_url', image_url: { url: 'data:image/png;base64,AA==' } },
        ] }),
      }, 1),
    ]);
    const steps = items.find((item) => item.kind === 'steps');
    expect(steps?.kind === 'steps' && steps.steps[0].imagePreview).toBe('data:image/png;base64,AA==');
  });

  it('shows the new-context divider in the timeline', () => {
    seq = 0;
    const items = buildTimeline([
      ev('context.window.switched' as AgentEvent['type'], {}, 1),
    ]);
    expect(items).toContainEqual(expect.objectContaining({ kind: 'notice', text: '已切换到新上下文' }));
  });

  it('caps huge tool outputs so a long session stays bounded', () => {
    seq = 0;
    const items = buildTimeline([
      ev('tool.started', { tool_call_id: 'big', name: 'local_shell', arguments: { command: 'npm test' } }),
      ev('tool.completed', { tool_call_id: 'big', name: 'local_shell', result: 'x'.repeat(20000) }, 1),
    ]);
    const steps = items.find((item) => item.kind === 'steps');
    const step = steps?.kind === 'steps' ? steps.steps[0] : undefined;
    expect(step?.result?.length ?? 0).toBeLessThan(10000);
    expect(step?.result).toContain('已截断');
  });

  it('does not repeat text Atlas said before a tool call when the final message arrives', () => {
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: '查一下' }),
      ev('message.delta', { content: '我来看看。' }),
      ev('tool.started', { tool_call_id: 'a', name: 'local_shell', arguments: { command: 'Get-Date' } }),
      ev('tool.completed', { tool_call_id: 'a', name: 'local_shell' }),
      ev('message.delta', { content: '现在是 10 点。' }),
      ev('message.completed', { content: '我来看看。现在是 10 点。' }),
    ]);
    const replies = items.flatMap((item) => item.kind === 'reply' ? [[item.content, item.streaming]] : []);
    expect(replies).toEqual([['我来看看。', false], ['现在是 10 点。', false]]);
  });

  it('marks a streamed reply as interrupted when an immediate redirect arrives', () => {
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: 'start' }),
      ev('message.delta', { content: 'partial output' }),
      ev('run.steered', { immediate: true, content: 'new direction' }),
    ]);
    expect(items).toContainEqual(expect.objectContaining({ kind: 'reply', content: 'partial output', status: '被用户打断' }));
  });

  it('renders validated structured components and replaces live updates by component id', () => {
    seq = 0;
    const items = buildTimeline([
      ev('component.push', { component_id: 'status', title: '部署', kind: 'progress', data: { steps: [{ label: '构建', status: 'active' }] } }),
      ev('component.push', { component_id: 'status', title: '部署', kind: 'progress', data: { steps: [{ label: '构建', status: 'done' }] } }),
      ev('component.push', { component_id: 'bad', title: '错误', kind: 'buttons', data: { buttons: [{ label: '无值' }] } }),
    ]);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ kind: 'component', component: { id: 'status', title: '部署', kind: 'progress', data: { steps: [{ status: 'done' }] } } });
  });
});

describe('C6 runtime events', () => {
  it('turns lsp.diagnostics into a quiet notice item with its real count and capped list', () => {
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: '修一下' }, 0),
      ev('lsp.diagnostics', {
        path: 'src/app.py', workspace: 'C:/ws', count: 2,
        diagnostics: [
          { line: 12, column: 5, severity: 'error', code: 'T999', message: 'oops' },
          { line: 30, column: 1, severity: 'hint', message: 'style' },
        ],
      }, 1),
    ]);
    const item = items.find((target) => target.kind === 'lsp');
    expect(item).toMatchObject({ kind: 'lsp', path: 'src/app.py', count: 2 });
    if (item?.kind === 'lsp') {
      expect(item.diagnostics).toHaveLength(2);
      expect(item.diagnostics[0]).toEqual({ line: 12, column: 5, severity: 'error', code: 'T999', message: 'oops' });
      expect(item.diagnostics[1]).toMatchObject({ severity: 'hint', code: undefined });
    }
  });

  it('keeps the true count when the backend truncates diagnostics to 20 and drops junk entries', () => {
    seq = 0;
    const items = buildTimeline([
      ev('lsp.diagnostics', {
        path: 'a.py', count: 23,
        diagnostics: [...Array.from({ length: 20 }, (_, index) => ({ line: index + 1, column: 1, severity: 'warning', message: 'w' })), 'junk', null],
      }, 1),
    ]);
    const item = items.find((target) => target.kind === 'lsp');
    expect(item?.kind === 'lsp' && item.count).toBe(23);
    expect(item?.kind === 'lsp' && item.diagnostics).toHaveLength(20);
  });

  it('never emits an lsp item for the zero-diagnostics case', () => {
    seq = 0;
    const items = buildTimeline([ev('lsp.diagnostics', { path: 'a.py', count: 0, diagnostics: [] }, 1)]);
    expect(items).toEqual([]);
  });

  it('turns review.findings into a review item, normalizing each finding', () => {
    seq = 0;
    const items = buildTimeline([
      ev('review.findings', {
        scope: 'working_tree', scope_label: '当前未提交改动', workspace: 'C:/ws',
        findings: [
          { file: 'src/app.py', line: 12, range: [12, 20], severity: 'blocker', title: '空指针', explanation: '可能为 None', evidence: 'x.foo', suggested_fix: '加判空' },
          { file: 'src/b.py', line: null, range: null, severity: ' nonsense', title: '命名', explanation: '', evidence: '', suggested_fix: '' },
          'junk',
        ],
      }, 1),
      ev('review.findings', { scope: 'branch', scope_label: '分支 dev 相对 main', findings: [] }, 2),
    ]);
    const reviews = items.filter((target) => target.kind === 'review');
    expect(reviews[0]).toMatchObject({ kind: 'review', scope: 'working_tree', scopeLabel: '当前未提交改动', workspace: 'C:/ws' });
    if (reviews[0]?.kind === 'review') {
      expect(reviews[0].findings).toHaveLength(2);
      expect(reviews[0].findings[0]).toEqual({ file: 'src/app.py', line: 12, range: [12, 20], severity: 'blocker', title: '空指针', explanation: '可能为 None', evidence: 'x.foo', suggested_fix: '加判空' });
      // 非法严重级落回 minor，缺失行号保持 null。
      expect(reviews[0].findings[1]).toMatchObject({ severity: 'minor', line: null, range: null });
    }
    expect(reviews[1]).toMatchObject({ kind: 'review', scopeLabel: '分支 dev 相对 main', findings: [] });
  });
});

describe('helpers', () => {
  it('shortens long paths and formats durations', () => {
    expect(shortPath('C:\\a\\b')).toBe('C:\\a\\b');
    expect(shortPath('/home/u/project/src/app.ts')).toBe('…/src/app.ts');
    expect(duration('2026-09-29T10:00:00Z', '2026-09-29T10:00:00.4Z')).toBe('不到 1 秒');
    expect(duration('2026-09-29T10:00:00Z', '2026-09-29T10:01:12Z')).toBe('1 分 12 秒');
  });
});

describe('protocol 1.3 events', () => {
  const at = (sequence: number) => new Date(Date.UTC(2026, 8, 30, 0, 0, sequence)).toISOString();
  const event = (type: string, data: Record<string, unknown>, sequence: number) => ({ id: `e${sequence}`, runId: 'r', sequence, type, timestamp: at(sequence), data }) as AgentEvent;

  it('shows rules after the request, steers as the user, and a plan card instead of its streamed text', () => {
    const items = buildTimeline([
      event('rules.loaded', { files: [{ path: 'C:\repo\AGENTS.md', bytes: 10 }] }, 1),
      event('run.started', { content: '加一行' }, 2),
      event('message.delta', { content: '计划如下……' }, 3),
      event('run.plan.proposed', { event_id: 'plan:r', plan: { goal: '加一行', subtasks: [] } }, 4),
      event('message.delta', { content: '已执行。' }, 5),
      event('run.steered', { content: '顺便看看 notes', event_id: 's1' }, 6),
      event('message.completed', { content: '已执行。' }, 7),
      event('run.completed', { usage: { input_tokens: 1200, output_tokens: 300 }, changes: { files: 1, additions: 1, deletions: 0 } }, 8),
    ]);
    expect(items.map((item) => item.kind)).toEqual(['user', 'steps', 'plan', 'reply', 'user', 'done']);
    expect(items[1]).toMatchObject({ steps: [{ verb: '读取项目规则' }] });
    expect(items[3]).toMatchObject({ content: '已执行。' });
    expect(items[4]).toMatchObject({ steered: true, content: '顺便看看 notes' });
    const done = items[5] as Extract<typeof items[number], { kind: 'done' }>;
    expect(tokenCount(done.usage)).toBe('1.5k');
    expect(done.changes).toEqual({ files: 1, additions: 1, deletions: 0 });
  });
});

describe('runtime notices', () => {
  it('explains a model switch and a verify-before-stop nudge in one plain line each', () => {
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: '修一下测试' }, 0),
      ev('run.model_switched', { from: 'dsv4.1flash', to: 'gpt-4o', reason: '请求过于频繁' }, 1),
      ev('run.verify_nudge', { changed_paths: ['C:\repo\src\a.py', 'b.py', 'c.py', 'd.py'] }, 2),
      ev('run.completed', {}, 3),
    ]);
    const notices = items.flatMap((item) => item.kind === 'notice' ? [[item.tone, item.text]] : []);
    expect(notices[0]).toEqual(['switch', 'dsv4.1flash 暂时用不了（请求过于频繁），已换成 gpt-4o 继续']);
    expect(notices[1][0]).toBe('verify');
    expect(notices[1][1]).toContain('等 4 个文件');
  });

  it('reports the cached share of input only when the provider said so', () => {
    expect(cacheShare({ input_tokens: 1000, cached_input_tokens: 620 })).toBe('缓存 62%');
    expect(cacheShare({ input_tokens: 1000, cached_input_tokens: 0 })).toBeNull();
    expect(cacheShare(undefined)).toBeNull();
  });
});

describe('restart recovery', () => {
  it('replaces the failure row a resumed run was persisted with, instead of stacking both', () => {
    // A restart marks the run failed; the resume then continues it under the
    // same run id. Showing "没能完成" above the resumed work would contradict it.
    seq = 0;
    const items = buildTimeline([
      ev('run.started', { content: '把这个页面做完' }, 0),
      ev('run.failed', { category: 'interrupted', detail: '服务重启了' }, 1),
      ev('run.status', { status: 'running' }, 2),
      ev('run.recovery.notice', { message: '已从中断处接着做', reason: 'service_restart', resume_attempt: 1 }, 3),
      ev('run.completed', {}, 4),
    ]);
    expect(items.map((item) => item.kind)).toEqual(['user', 'notice', 'done']);
    expect(items[1]).toMatchObject({ tone: 'switch', text: '已从中断处接着做' });
  });

  it('keeps a genuine failure when the notice is about something else', () => {
    // Only a restart resume supersedes the failure; every other recovery
    // notice follows a failure that really did end the run.
    seq = 0;
    const items = buildTimeline([
      ev('run.failed', { category: 'interrupted', detail: '服务重启了' }, 1),
      ev('run.recovery.notice', { message: '工作区需要一个新目录', reason: 'workspace_root' }, 2),
    ]);
    expect(items.map((item) => item.kind)).toEqual(['failed', 'notice']);
  });
});
