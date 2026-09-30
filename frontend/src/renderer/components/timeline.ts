import type { AgentEvent } from '../../types/runtime';

/**
 * Turns the raw runtime event stream into what a person wants to read:
 * their message, the steps Atlas took (in plain words), approvals, the reply, and the outcome.
 * Internal bookkeeping events (status, phase, plan) never reach the thread.
 */

export type StepState = 'running' | 'done' | 'failed' | 'cancelled';

export interface Step {
  id: string;
  verb: string;
  target?: string;
  state: StepState;
  startedAt: string;
  endedAt?: string;
  input?: string;
  result?: string;
  output: string;
}

export interface RunUsage { input_tokens?: number | null; output_tokens?: number | null; context_tokens?: number | null; context_limit?: number | null }
export interface RunChanges { files: number; additions: number; deletions: number }

export type TimelineItem =
  | { kind: 'user'; id: string; content: string; steered?: boolean }
  | { kind: 'reply'; id: string; content: string; streaming: boolean }
  | { kind: 'steps'; id: string; steps: Step[] }
  | { kind: 'approval'; id: string; event: AgentEvent }
  | { kind: 'question'; id: string; event: AgentEvent }
  | { kind: 'plan'; id: string; event: AgentEvent }
  | { kind: 'cancelled'; id: string }
  | { kind: 'artifact'; id: string; name: string; summary: string }
  | { kind: 'done'; id: string; result: string; startedAt?: string; endedAt: string; usage?: RunUsage; changes?: RunChanges }
  | { kind: 'failed'; id: string; detail: string };

const TARGET_KEYS = ['path', 'file_path', 'filepath', 'file', 'command', 'cmd', 'query', 'pattern', 'url', 'q', 'target', 'name'];

const VERBS: Array<[RegExp, string]> = [
  [/screenshot|screen_?shot|capture/, '截取屏幕'],
  [/click|type_text|keyboard|mouse|computer|pywinauto|cua/, '操作电脑'],
  [/list_?dir|ls\b|glob|tree/, '查看目录'],
  [/read|view|cat\b|get_?file|open_?file/, '读取'],
  [/write|create_?file|save/, '写入'],
  [/edit|patch|replace|apply|modify/, '修改'],
  [/delete|remove|unlink|rm\b/, '删除'],
  [/git/, 'Git'],
  [/shell|exec|command|bash|powershell|terminal|process|run/, '运行命令'],
  [/web_?search|search_?web|bing|google/, '搜索网页'],
  [/grep|search|find|query/, '搜索'],
  [/fetch|http|navigate|browser|url|page|playwright|devtools/, '打开网页'],
  [/memory|remember|recall/, '查看记忆'],
  [/image|draw|generate/, '生成图像'],
];

function pickTarget(args: unknown): string | undefined {
  if (typeof args === 'string') return args.slice(0, 120);
  if (!args || typeof args !== 'object') return undefined;
  const record = args as Record<string, unknown>;
  for (const key of TARGET_KEYS) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim().replace(/\s+/g, ' ').slice(0, 120);
    if (Array.isArray(value) && value.length && typeof value[0] === 'string') return value.join(' ').slice(0, 120);
  }
  return undefined;
}

/** Long Windows/POSIX paths keep their tail, which is the part people recognise. */
export function shortPath(path: string): string {
  const parts = path.split(/[\\/]+/).filter(Boolean);
  if (parts.length <= 3) return path;
  const separator = path.includes('\\') ? '\\' : '/';
  return `…${separator}${parts.slice(-2).join(separator)}`;
}

const FILE_ACTIONS: Record<string, string> = {
  read: '读取', write: '写入', append: '追加写入', mkdir: '新建文件夹', copy: '复制', move: '移动', delete: '删除',
  list: '查看目录', glob: '查找文件', search: '搜索文件内容', stat: '查看文件信息',
};
const PROCESS_ACTIONS: Record<string, string> = {
  start: '启动进程', status: '查看进程状态', read: '读取进程输出', wait: '等待进程结束', cancel: '停止进程', list: '查看进程列表',
};
const GIT_ACTIONS: Record<string, string> = {
  status: '查看 Git 状态', diff: '查看改动', log: '查看提交记录', branch: '查看分支', add: '暂存改动',
  commit: '提交改动', pull: '拉取代码', fetch: '获取远程更新', push: '推送代码',
};

/** Plain-language verb + salient argument for a tool call, e.g. `local_shell {command: "npm test"}` → 运行命令 npm test. */
export function describeTool(name: string, args: unknown): { verb: string; target?: string } {
  const a = args && typeof args === 'object' ? args as Record<string, unknown> : {};
  const str = (value: unknown) => typeof value === 'string' && value.trim() ? value.trim() : undefined;
  const action = str(a.action);
  switch (name) {
    case 'local_file':
      return { verb: FILE_ACTIONS[action ?? ''] ?? '处理文件', target: action === 'search' ? str(a.query) ?? str(a.pattern) : str(a.path) && shortPath(str(a.path)!) };
    case 'local_edit':
      return { verb: '修改', target: str(a.path) && shortPath(str(a.path)!) };
    case 'local_shell':
      return { verb: '运行命令', target: str(a.command)?.slice(0, 120) };
    case 'local_exec':
      return { verb: '运行', target: [str(a.executable), ...(Array.isArray(a.args) ? a.args.map(String) : [])].filter(Boolean).join(' ').slice(0, 120) };
    case 'local_process':
      return { verb: PROCESS_ACTIONS[action ?? ''] ?? '管理进程', target: str(a.command) ?? str(a.executable) };
    case 'local_git':
      return { verb: GIT_ACTIONS[action ?? ''] ?? 'Git 操作', target: str(a.repo) && shortPath(str(a.repo)!) };
    default: {
      const key = name.toLowerCase();
      const verb = VERBS.find(([pattern]) => pattern.test(key))?.[1];
      const target = pickTarget(args);
      if (verb) return { verb, target };
      return { verb: '使用工具', target: target ? `${name} ${target}` : name };
    }
  }
}

const text = (value: unknown) => typeof value === 'string' ? value : value === undefined || value === null ? '' : JSON.stringify(value, null, 2);

export function buildTimeline(events: AgentEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const byExecution = new Map<string, Step>();
  let track: { kind: 'steps'; id: string; steps: Step[] } | null = null;
  let reply: { kind: 'reply'; id: string; content: string; streaming: boolean } | null = null;
  let runStartedAt: string | undefined;
  let earlyRules: Step | null = null;
  // Text Atlas streamed before a tool call. The final message.completed repeats it, so it is trimmed off there.
  let spoken = '';
  const closeReply = () => { if (reply) { reply.streaming = false; spoken += reply.content; reply = null; } };

  const stepsBlock = (id: string) => {
    if (!track) { track = { kind: 'steps', id: `steps-${id}`, steps: [] }; items.push(track); }
    return track;
  };
  const closeBlocks = () => { track = null; };

  for (const event of events) {
    const data = event.data;
    switch (event.type) {
      case 'run.started':
        runStartedAt = event.timestamp;
        if (typeof data.content === 'string' && data.content) items.push({ kind: 'user', id: event.id, content: data.content });
        closeBlocks(); reply = null; spoken = '';
        // The backend reports loaded rules just before the run starts; show them after the request.
        if (earlyRules) { stepsBlock(earlyRules.id).steps.push(earlyRules); earlyRules = null; }
        break;
      case 'tool.started': {
        const key = String(data.tool_call_id || data.call_id || event.id);
        const { verb, target } = describeTool(String(data.name ?? '工具'), data.arguments ?? data.input);
        const step: Step = { id: event.id, verb, target, state: 'running', startedAt: event.timestamp, input: text(data.arguments ?? data.input), output: '' };
        byExecution.set(key, step);
        if (!data.tool_call_id) byExecution.set(`name:${String(data.name)}`, step);
        closeReply();
        stepsBlock(event.id).steps.push(step);
        break;
      }
      case 'tool.completed': {
        const execution = data.execution && typeof data.execution === 'object' ? data.execution as Record<string, unknown> : undefined;
        const key = String(data.tool_call_id || data.call_id || '');
        let step = (key && byExecution.get(key)) || byExecution.get(`name:${String(data.name)}`);
        if (!step || step.state !== 'running') {
          const { verb, target } = describeTool(String(data.name ?? '工具'), data.arguments ?? execution?.command);
          step = { id: event.id, verb, target, state: 'running', startedAt: event.timestamp, input: text(data.arguments), output: '' };
          stepsBlock(event.id).steps.push(step);
        }
        step.state = execution?.state === 'cancelled' ? 'cancelled' : data.is_error ? 'failed' : 'done';
        step.endedAt = event.timestamp;
        step.result = text(data.result);
        if (execution) {
          const parts = [execution.stdout, execution.stderr].map(text).filter(Boolean);
          if (parts.length && !step.output) step.output = parts.join('\n');
        }
        break;
      }
      case 'tool.output': {
        const step = byExecution.get(String(data.tool_call_id ?? '')) ?? byExecution.get(`name:${String(data.name)}`);
        if (step) step.output += String(data.text ?? '');
        break;
      }
      case 'artifact.updated':
        items.push({ kind: 'artifact', id: event.id, name: String(data.name ?? data.path ?? '文件'), summary: String(data.summary ?? data.change ?? '') });
        closeBlocks();
        break;
      case 'approval.required':
        items.push({ kind: 'approval', id: event.id, event });
        closeBlocks();
        break;
      case 'message.delta':
        if (!reply) { reply = { kind: 'reply', id: event.id, content: '', streaming: true }; items.push(reply); closeBlocks(); }
        reply.content += String(data.content ?? '');
        break;
      case 'message.completed': {
        const full = String(data.content ?? reply?.content ?? '');
        const body = spoken && full.startsWith(spoken) ? full.slice(spoken.length).trimStart() : full;
        if (reply) { reply.content = body; reply.streaming = false; }
        else if (body.trim()) items.push({ kind: 'reply', id: event.id, content: body, streaming: false });
        reply = null; closeBlocks();
        break;
      }
      case 'run.steered':
        closeReply(); closeBlocks();
        items.push({ kind: 'user', id: event.id, content: String(data.content ?? ''), steered: true });
        break;
      case 'rules.loaded': {
        const files = Array.isArray(data.files) ? data.files as Array<{ path?: string }> : [];
        if (!files.length) break;
        const step: Step = {
          id: event.id, verb: '读取项目规则', target: files.map((file) => shortPath(String(file.path ?? ''))).join('、'),
          state: 'done', startedAt: event.timestamp, endedAt: event.timestamp, output: '',
        };
        if (runStartedAt) stepsBlock(event.id).steps.push(step); else earlyRules = step;
        break;
      }
      case 'input.required':
        closeReply(); closeBlocks();
        items.push({ kind: 'question', id: event.id, event });
        break;
      case 'run.plan.proposed':
        // The plan's text was streamed as the reply; the card below replaces it.
        if (reply) { items.splice(items.indexOf(reply), 1); reply = null; }
        // Execution after approval is a fresh turn whose final message repeats only its own text.
        spoken = '';
        closeBlocks();
        items.push({ kind: 'plan', id: event.id, event });
        break;
      case 'run.completed':
        items.push({
          kind: 'done', id: event.id, result: text(data.result), startedAt: runStartedAt, endedAt: event.timestamp,
          usage: data.usage && typeof data.usage === 'object' ? data.usage as RunUsage : undefined,
          changes: data.changes && typeof data.changes === 'object' ? data.changes as RunChanges : undefined,
        });
        break;
      case 'run.cancelled':
        closeReply();
        items.push({ kind: 'cancelled', id: event.id });
        break;
      case 'run.failed':
        items.push({ kind: 'failed', id: event.id, detail: text(data.detail ?? data.code) || '未知错误' });
        break;
      default:
        break;
    }
  }
  return items;
}

/** "1.2k" style token counts; null when the provider did not report usage. */
export function tokenCount(usage?: RunUsage): string | null {
  const total = (usage?.input_tokens ?? 0) + (usage?.output_tokens ?? 0);
  if (!usage || (usage.input_tokens == null && usage.output_tokens == null) || !total) return null;
  return total >= 1000 ? `${(total / 1000).toFixed(total >= 10_000 ? 0 : 1)}k` : String(total);
}

export function duration(from?: string, to?: string): string {
  if (!from || !to) return '';
  const seconds = Math.max(0, (new Date(to).getTime() - new Date(from).getTime()) / 1000);
  if (seconds < 1) return '不到 1 秒';
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  return `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
}
