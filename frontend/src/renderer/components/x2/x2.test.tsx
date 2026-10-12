import { afterEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import type { AgentEvent } from '../../../types/runtime';
import { normalizeRuntimeEvent } from '../../services/runtimeEvents';
import {
  addVaultEntry, controlBrowserRecording, deleteVaultEntry, normalizeEntries, pauseComputer,
  resolveBrowserHandoff, resolveForeground, recordingToSkill, type VaultEntry,
} from '../../services/x2Api';
import ComputerEdgeBar from './ComputerEdgeBar';
import ComputerReplayPanel, { ComputerStepList } from './ComputerReplayPanel';
import ComputerStatusSection, { ComputerDiagnostics } from './ComputerStatusSection';
import ForegroundConfirmCard from './ForegroundConfirmCard';
import BrowserHandoffCard from './BrowserHandoffCard';
import BrowserRecorderPanel, { SkillForm, SkillPreview, browserStepsFromEvents } from './BrowserRecorderPanel';
import BrowserSettingsSection, { BROWSER_MODES, VaultManager } from './BrowserSettingsSection';

const event = (type: AgentEvent['type'], data: Record<string, unknown> = {}, sequence = 1): AgentEvent =>
  ({ id: `e${sequence}`, runId: 'run-1', sequence, type, timestamp: '2026-10-03T00:00:00Z', data });

const fetchJson = (status = 200, body: unknown = {}) =>
  vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify(body), { status }));

afterEach(() => vi.unstubAllGlobals());

describe('X2 runtime event wiring', () => {
  const cases: Array<[AgentEvent['type'], Record<string, unknown>]> = [
    ['computer.foreground_required', { reason: '需要在微信窗口里点击发送' }],
    ['computer.foreground_resumed', { reason: '鼠标已离开' }],
    ['computer.step', { index: 1, action: '点击', target: '发送' }],
    ['browser.handoff_required', { reason: '页面要求登录', url: 'https://example.com' }],
    ['browser.handoff_resolved', { resolution: 'done' }],
    ['browser.panel.sync', { url: 'https://example.com' }],
    ['browser.step', { index: 2, action: '填写', target: '#kw' }],
  ];
  it('recognizes the seven new X2 wire events so they reach run.events', () => {
    for (const [type, data] of cases) {
      const normalized = normalizeRuntimeEvent({
        type: 'agent_event', event_id: `run-1:${data.index ?? 1}`, run_id: 'run-1', sequence: Number(data.index ?? 1) || 1,
        timestamp: '2026-10-03T00:00:00Z', event: type, data,
      });
      expect(normalized?.type).toBe(type);
      expect(normalized?.data).toEqual(data);
    }
  });
  it('still rejects unknown events', () => {
    expect(normalizeRuntimeEvent({
      type: 'agent_event', event_id: 'run-1:99', run_id: 'run-1', sequence: 99,
      timestamp: '2026-10-03T00:00:00Z', event: 'computer.something_else', data: {},
    })).toBeNull();
  });
});

describe('ForegroundConfirmCard', () => {
  it('shows the reason, the target window and the 批准/拒绝 pair', () => {
    const html = renderToStaticMarkup(
      <ForegroundConfirmCard apiBaseUrl="http://x" runId="run-1" reason="需要在微信窗口里点击发送" target="微信" />,
    );
    expect(html).toContain('Atlas 想在你正在使用的窗口里操作');
    expect(html).toContain('需要在微信窗口里点击发送');
    expect(html).toContain('微信');
    expect(html).toContain('批准');
    expect(html).toContain('拒绝');
  });
});

describe('ComputerEdgeBar', () => {
  it('offers stopping on Windows and only offers pause when the driver supports it', () => {
    const html = renderToStaticMarkup(<ComputerEdgeBar apiBaseUrl="http://x" runId="run-1" />);
    expect(html).toContain('电脑操控进行中 — Windows 使用当前前台桌面');
    expect(html).toContain('停止');
    expect(html).not.toContain('暂停操作');
    const pausable = renderToStaticMarkup(<ComputerEdgeBar apiBaseUrl="http://x" runId="run-1" canPause />);
    expect(pausable).toContain('暂停操作');
  });
});

describe('ComputerReplayPanel', () => {
  it('lists steps with index, thumbnail and action text', () => {
    const html = renderToStaticMarkup(<ComputerStepList steps={[
      { index: 1, action: '点击', target: '发送按钮', thumbnail: 'data:image/png;base64,AAAA' },
      { action: '输入文本', target: '搜索框' },
    ]} />);
    expect((html.match(/<li /g) ?? []).length).toBe(2);
    expect(html).toContain('src="data:image/png;base64,AAAA"');
    expect(html).toContain('点击');
    expect(html).toContain('发送按钮');
    expect(html).toContain('输入文本');
    expect(html).toContain('第 1 步截图');
  });
  it('explains when there is nothing to replay', () => {
    expect(renderToStaticMarkup(<ComputerStepList steps={[]} />)).toContain('还没有可回放的步骤');
  });
  it('hints that a run must be chosen before loading steps', () => {
    expect(renderToStaticMarkup(<ComputerReplayPanel apiBaseUrl="http://x" />)).toContain('还没有选择要回放的电脑操控任务');
  });
});

describe('BrowserHandoffCard', () => {
  it('shows reason, URL and the three resolution buttons', () => {
    const html = renderToStaticMarkup(
      <BrowserHandoffCard apiBaseUrl="http://x" runId="run-1" reason="页面要求登录" url="https://example.com/login" />,
    );
    expect(html).toContain('浏览器这一步需要你搭把手');
    expect(html).toContain('页面要求登录');
    expect(html).toContain('https://example.com/login');
    expect(html).toContain('在浏览器面板打开');
    expect(html).toContain('我弄好了，继续');
    expect(html).toContain('做不了');
  });
});

describe('BrowserRecorderPanel', () => {
  const steps = [
    event('browser.step', { index: 1, action: '打开页面', url: 'https://example.com' }, 1),
    event('browser.step', { index: 2, action: '填写', target: '#kw' }, 2),
    event('tool.completed', {}, 3), // 非 X2 事件不应混进来
  ];
  it('derives steps only from browser.step events and keeps run scoping', () => {
    expect(browserStepsFromEvents(steps).map((step) => step.action)).toEqual(['打开页面', '填写']);
    expect(browserStepsFromEvents(steps, 'other-run')).toEqual([]);
    // 缺 index/action 的退化事件也能整理出可读的一行
    expect(browserStepsFromEvents([event('browser.step', {}, 9)])[0]).toMatchObject({ index: 1, action: '浏览器操作' });
    // 重复推送（断线重放）按事件 id 去重
    expect(browserStepsFromEvents([...steps, steps[0]]).length).toBe(2);
  });
  it('renders the live step list, the start button and the recording badge', () => {
    const html = renderToStaticMarkup(<BrowserRecorderPanel apiBaseUrl="http://x" events={steps} />);
    expect(html).toContain('浏览器操作录制');
    expect(html).toContain('开始录制');
    expect(html).toContain('打开页面');
    expect(html).toContain('#kw');
    expect(html).not.toContain('录制中');
  });
  it('offers the save-as-skill flow with a SKILL.md preview before saving', () => {
    const html = renderToStaticMarkup(<SkillForm apiBaseUrl="http://x" recordingId="rec-1" />);
    expect(html).toContain('技能名称');
    expect(html).toContain('生成预览');
    expect(html).toContain('保存为技能');
    // 预览块独立成组件：拿到 dry_run 结果后给人过目，再决定保存
    const preview = renderToStaticMarkup(<SkillPreview preview={{ skill_md: '---\nname: demo\n---\n1. 打开页面' }} />);
    expect(preview).toContain('SKILL.md 预览');
    expect(preview).toContain('1. 打开页面');
    expect(renderToStaticMarkup(<SkillPreview preview={{ skill_md: undefined }} />)).toBe('');
  });
});

describe('BrowserSettingsSection', () => {
  it('offers exactly the four takeover modes plus CDP and proxy inputs', () => {
    expect(BROWSER_MODES.map((mode) => mode.value)).toEqual(['standalone', 'copied-profile', 'cdp', 'extension']);
    const html = renderToStaticMarkup(<BrowserSettingsSection apiBaseUrl="http://x" />);
    expect(html).toContain('独立浏览器');
    expect(html).toContain('复制本机配置');
    expect(html).toContain('连接已打开的浏览器（CDP）');
    expect(html).toContain('浏览器扩展');
    expect(html).toContain('保存设置');
    // CDP 输入框只在选择了 cdp 模式时出现
    expect(html).not.toContain('CDP 调试地址');
  });
  it('shows the CDP endpoint input only in cdp mode', () => {
    const html = renderToStaticMarkup(
      <BrowserSettingsSection apiBaseUrl="http://x" initialSettings={{ mode: 'cdp', cdp_url: 'http://127.0.0.1:9222', proxy: '' }} />,
    );
    expect(html).toContain('CDP 调试地址');
    expect(html).toContain('value="http://127.0.0.1:9222"');
    expect(html).toContain('remote-debugging-port');
  });
  it('lists vault entries as handles only and never echoes the password', () => {
    const html = renderToStaticMarkup(
      <VaultManager entries={[{ id: 'v1', label: '公司 OA', username: 'zhang', url: 'https://oa.example.com' }]}
        busy={false} onAdd={vi.fn(async () => true)} onDelete={vi.fn()} />,
    );
    expect(html).toContain('公司 OA');
    expect(html).toContain('zhang');
    expect(html).toContain('https://oa.example.com');
    expect(html).toContain('删除');
    // 密码既不回显在列表里，新增框也始终是 password 类型
    expect(html).not.toContain('S3cret-密码');
    expect(html).toContain('type="password"');
    expect(html).toContain('密码保存后不会再显示');
  });
});

describe('ComputerStatusSection', () => {
  it('shows the probing hint before the status arrives', () => {
    expect(renderToStaticMarkup(<ComputerStatusSection apiBaseUrl="http://x" />)).toContain('正在探测…');
  });
  it('renders readiness, driver and per-item diagnostics', () => {
    const html = renderToStaticMarkup(<ComputerDiagnostics items={[
      { name: '屏幕读取', ok: true, detail: '正常' },
      { name: '键鼠注入', ok: false, detail: '需要管理员权限' },
    ]} />);
    expect(html).toContain('屏幕读取');
    expect(html).toContain('需要管理员权限');
  });
});

describe('X2 API client', () => {
  it('posts the approval decision with run_id to /api/computer/foreground', async () => {
    const f = fetchJson(200, { status: 'ok' });
    vi.stubGlobal('fetch', f);
    await resolveForeground('http://x', 'run-9', true);
    const [input, init] = f.mock.calls[0];
    expect(String(input)).toBe('http://x/api/computer/foreground');
    expect(JSON.parse(String(init?.body))).toEqual({ run_id: 'run-9', approve: true });
  });
  it('pauses the foreground operation with run_id', async () => {
    const f = fetchJson();
    vi.stubGlobal('fetch', f);
    await pauseComputer('http://x', 'run-9');
    const [input, init] = f.mock.calls[0];
    expect(String(input)).toBe('http://x/api/computer/pause');
    expect(JSON.parse(String(init?.body))).toEqual({ run_id: 'run-9' });
  });
  it('sends the handoff resolution verbatim', async () => {
    const f = fetchJson();
    vi.stubGlobal('fetch', f);
    await resolveBrowserHandoff('http://x', 'run-9', 'open_panel');
    expect(JSON.parse(String(f.mock.calls[0][1]?.body))).toEqual({ run_id: 'run-9', resolution: 'open_panel' });
  });
  it('starts and stops recordings, keeping the session id on stop', async () => {
    const f = fetchJson(200, { recording_id: 'rec-2' });
    vi.stubGlobal('fetch', f);
    await controlBrowserRecording('http://x', 'start');
    expect(JSON.parse(String(f.mock.calls[0][1]?.body))).toEqual({ action: 'start' });
    await controlBrowserRecording('http://x', 'stop', 'rec-2');
    expect(JSON.parse(String(f.mock.calls[1][1]?.body))).toEqual({ action: 'stop', recording_id: 'rec-2' });
  });
  it('previews and saves a recording as a skill (dry_run toggles)', async () => {
    const f = fetchJson(200, { skill_md: '---\nname: demo\n---' });
    vi.stubGlobal('fetch', f);
    await recordingToSkill('http://x', 'rec-2', { dry_run: true, name: 'demo' });
    const [input, init] = f.mock.calls[0];
    expect(String(input)).toBe('http://x/api/browser/recordings/rec-2/to-skill');
    expect(JSON.parse(String(init?.body))).toEqual({ dry_run: true, name: 'demo' });
  });
  it('posts the vault password exactly once and deletes by encoded id', async () => {
    const f = fetchJson(200, { id: 'v9', label: 'OA' });
    vi.stubGlobal('fetch', f);
    await addVaultEntry('http://x', { label: 'OA', username: 'zhang', password: 'S3cret-密码' });
    const [addInput, addInit] = f.mock.calls[0];
    expect(String(addInput)).toBe('http://x/api/browser/vault');
    expect(JSON.parse(String(addInit?.body))).toMatchObject({ label: 'OA', password: 'S3cret-密码' });
    await deleteVaultEntry('http://x', 'v/9');
    const [delInput, delInit] = f.mock.calls[1];
    expect(String(delInput)).toBe('http://x/api/browser/vault/v%2F9');
    expect(delInit?.method).toBe('DELETE');
  });
  it('surfaces backend errors in Chinese and accepts both vault list shapes', async () => {
    vi.stubGlobal('fetch', fetchJson(400, { detail: '缺参数' }));
    await expect(resolveForeground('http://x', 'run-9', false)).rejects.toThrow('HTTP 400：缺参数');
    const wrapped: { entries: VaultEntry[] } = { entries: [{ id: 'v1', label: 'OA' }] };
    expect(normalizeEntries(wrapped)).toHaveLength(1);
    expect(normalizeEntries([{ id: 'v2', label: 'OA' }])).toHaveLength(1);
    expect(normalizeEntries(undefined)).toEqual([]);
  });
});
