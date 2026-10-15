export const MOCK_MEMLIB_ENABLED = false;

export type MemlibKind = 'fact' | 'episode' | 'diary' | 'dream' | 'raw';
export type MemlibItem = {
  id: string; kind: MemlibKind; path: string; title: string; text: string; snippet: string;
  src: string; at: string; ref: string; score: number; project: string;
};
export type Episode = {
  id: string; day: string; at: string; session: string; ref: string; text: string; outcome: string;
  verified: boolean; steps: string[]; decisions: string[]; files: string[]; commands: string[];
  facts: string[]; open_items: string[]; trigger: string[];
};
export type ProjectSummary = { path: string; title: string; count: number; updated: string; open_items: number };
export type Entry = { id: string; text: string; src: string; at: string; ref?: string; why?: string };
export type Project = {
  path: string; title: string; aliases: string[];
  sections: Record<'现在状态' | '定下的决定' | '没做完' | '来龙去脉', Entry[]>;
  history: Entry[];
};
export type OpenResult = {
  ok: boolean; session: string; title: string;
  messages: Array<{ role?: string; text?: string; at?: string; tool?: { name: string; ok?: boolean; args?: string; output?: string } }>;
  truncated: boolean;
};
export type Stats = {
  facts: number; episodes: number; projects: number; diary_days: number; today_added: number;
  last_dream: string | null; pending_failed: number; embed: 'ready' | 'building' | 'unavailable';
};

const start = new Date('2026-10-16T01:12:00+08:00').getTime();
const projects = ['Atlas 记忆库', 'Atlas 联网搜索', 'Atlas 竞品', 'DeepSeek Harness', 'AIPlan'];
const samples = [
  'W2 记忆浏览器实现了虚拟滚动，保留出处和原文跳转。',
  '项目约定：每次改动先查当前分支与工作区状态。',
  '确认使用本地向量索引，避免额外运行一个服务。',
  '今天检查了页面布局、搜索条件和时间范围筛选。',
  '尚未完成：补齐原始会话来源和性能记录。',
  '执行结果通过构建确认，异常输出保留在变更记录。',
  '决定每条经历保留文件、命令、关键数字和未完成项。',
  '用户偏好中文沟通，界面文案也使用简体中文。',
];
const sourceNames = ['你说的', '你改的', '推测', '经历', '整理', '原对话'];
const srcKey: Record<string, string> = { '你说的': '你说的', '你改的': '你改的', '推测': '推测', '经历': '经历', '整理': '整理', '原对话': '原对话' };

function mockItem(index: number): MemlibItem {
  const at = new Date(start - index * 12 * 60_000).toISOString();
  const project = projects[index % projects.length];
  const kind: MemlibKind = index % 5 === 0 ? 'episode' : index % 7 === 0 ? 'raw' : index % 3 === 0 ? 'dream' : 'fact';
  const text = samples[index % samples.length];
  return {
    id: `mock-${index}`, kind, path: kind === 'episode' ? `经历/${at.slice(0, 10)}.md` : `事/${project}.md`,
    title: `${project} · ${['实现记录', '检索方案', '验证结果', '项目约定'][index % 4]}`,
    text, snippet: text, src: srcKey[sourceNames[index % sourceNames.length]], at,
    ref: `mock-session-${index}`, score: 1 - (index % 1000) / 10000, project,
  };
}

const mockItems = Array.from({ length: 20_000 }, (_, index) => mockItem(index));
export const mockStats: Stats = {
  facts: 16_360, episodes: 3_640, projects: 37, diary_days: 1_221, today_added: 27,
  last_dream: '2026-10-16T03:30:00+08:00', pending_failed: 0, embed: 'ready',
};
export const mockMemlib = {
  search(params: URLSearchParams) {
    const q = (params.get('q') ?? '').trim().toLocaleLowerCase();
    const sources = (params.get('src') ?? '').split(',').filter(Boolean);
    const project = params.get('project') ?? '';
    const from = params.get('from') ?? '';
    const to = params.get('to') ?? '';
    const filtered = mockItems.filter((item) =>
      (!q || `${item.title} ${item.text} ${item.project}`.toLocaleLowerCase().includes(q)) &&
      (!sources.length || sources.includes(item.src)) && (!project || item.project === project) &&
      (!from || item.at.slice(0, 10) >= from) && (!to || item.at.slice(0, 10) <= to));
    const offset = Number(params.get('offset') ?? 0);
    return { total: filtered.length, items: filtered.slice(offset, offset + Number(params.get('limit') ?? 30)) };
  },
  timeline(before: string | null, limit: number) {
    const items = mockItems.filter((item) => item.kind === 'episode' && (!before || item.at < before)).slice(0, limit);
    const episodes: Episode[] = items.map((item) => ({
      id: item.id, day: item.at.slice(0, 10), at: item.at, session: item.ref, ref: item.ref,
      text: item.title, outcome: item.text, verified: Number(item.id.slice(5)) % 2 === 0,
      steps: ['读取原文与项目页', '保存实现结果'], decisions: ['记忆项带有可打开的来源指针'],
      files: [item.path], commands: [], facts: ['20,000 条 mock 记录'], open_items: [], trigger: [],
    }));
    return { items: episodes, next: items.length ? items[items.length - 1].at : null };
  },
  projects(): ProjectSummary[] {
    return projects.map((title, index) => ({ path: `事/${title}.md`, title, count: 23 - index, updated: new Date(start - index * 86_400_000).toISOString(), open_items: index % 3 }));
  },
  project(path: string): Project {
    const title = path.replace(/^事\//, '').replace(/\.md$/, '');
    const entry = (id: string, text: string, src = 'dream'): Entry => ({ id, text, src, at: new Date(start).toISOString(), ref: id });
    return { path, title, aliases: [], sections: {
      '现在状态': [entry('mock-project-now', `${title}：${samples[0]}`)],
      '定下的决定': [entry('mock-project-decision', samples[2], 'said')],
      '没做完': [entry('mock-project-open', samples[4])],
      '来龙去脉': [entry('mock-project-history', samples[6])],
    }, history: [] };
  },
  open(ref: string): OpenResult {
    const index = Number(ref.replace('mock-session-', '')) || 0;
    return { ok: true, session: ref, title: `Mock 对话 ${index}`, truncated: false, messages: [
      { role: 'user', text: '请保留记忆的细节和出处。', at: new Date(start).toISOString() },
      { role: 'assistant', text: mockItem(index).text, at: new Date(start + 30_000).toISOString() },
      { tool: { name: 'memory_search', ok: true, args: `ref=${ref}`, output: '来源片段已展开。' } },
    ] };
  },
};
