import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import { buildTimeline, describeTool, duration, shortPath } from './timeline';

let seq = 0;
const ev = (type: AgentEvent['type'], data: Record<string, unknown>, second = seq): AgentEvent =>
  ({ id: `e${++seq}`, runId: 'r1', sequence: seq, type, timestamp: new Date(Date.UTC(2026, 8, 29, 10, 0, second)).toISOString(), data });

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
});

describe('helpers', () => {
  it('shortens long paths and formats durations', () => {
    expect(shortPath('C:\\a\\b')).toBe('C:\\a\\b');
    expect(shortPath('/home/u/project/src/app.ts')).toBe('…/src/app.ts');
    expect(duration('2026-09-29T10:00:00Z', '2026-09-29T10:00:00.4Z')).toBe('不到 1 秒');
    expect(duration('2026-09-29T10:00:00Z', '2026-09-29T10:01:12Z')).toBe('1 分 12 秒');
  });
});
