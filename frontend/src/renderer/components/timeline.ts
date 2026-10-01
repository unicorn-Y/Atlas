import type { CheckResults } from '@atlas/backend-adapter';
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
  /** Set for delegated sub-agents, which can be cancelled on their own. */
  subtaskId?: string;
  /** Sub-agent details: type (explore, verifier…), model, running in the background, nesting level, recipe. */
  agent?: { type?: string; model?: string; background?: boolean; depth?: number; recipe?: string };
  /** Extra instructions you sent to this sub-agent while it ran. */
  steers?: string[];
  /** A short note under the step, e.g. that an instruction arrived too late. */
  note?: string;
  /** Where the backend saved a tool result too large for the model's context. */
  fullOutputPath?: string;
}

export interface RunUsage { input_tokens?: number | null; output_tokens?: number | null; cached_input_tokens?: number | null; context_tokens?: number | null; context_limit?: number | null }
export interface RunChanges { files: number; additions: number; deletions: number }

export type TimelineItem =
  | { kind: 'user'; id: string; content: string; steered?: boolean; moa?: boolean }
  | { kind: 'reply'; id: string; content: string; streaming: boolean }
  | { kind: 'steps'; id: string; steps: Step[] }
  | { kind: 'approval'; id: string; event: AgentEvent }
  | { kind: 'question'; id: string; event: AgentEvent }
  | { kind: 'plan'; id: string; event: AgentEvent }
  | { kind: 'trust'; id: string; event: AgentEvent }
  | { kind: 'group'; id: string; summary: string; results: Array<{ index: number; title: string; status: string; summary: string; changed_files: string[]; verified?: boolean; verifier_note?: string }> }
  | { kind: 'background'; id: string; summary: string }
  | { kind: 'moa'; id: string; latencyMs: number; references: Array<{ model: string; text: string }> }
  | { kind: 'checks'; id: string; results: CheckResults }
  | { kind: 'cancelled'; id: string }
  /** One-line runtime notes: the model was swapped after errors, or Atlas went back to verify its edits. */
  | { kind: 'notice'; id: string; tone: 'switch' | 'verify'; text: string }
  | { kind: 'artifact'; id: string; name: string; summary: string }
  | { kind: 'done'; id: string; result: string; startedAt?: string; endedAt: string; usage?: RunUsage; changes?: RunChanges }
  | { kind: 'failed'; id: string; detail: string };

/** A message sent as `/moa …` asks for a multi-model consultation; show it without the prefix. */
export function splitMoa(content: string): { moa: boolean; text: string } {
  const match = /^\s*\/moa(?:\s+|$)/.exec(content);
  return match ? { moa: true, text: content.slice(match[0].length) } : { moa: false, text: content };
}

const TARGET_KEYS = ['path', 'file_path', 'filepath', 'file', 'command', 'cmd', 'query', 'pattern', 'url', 'q', 'target', 'name'];

const VERBS: Array<[RegExp, string]> = [
  [/^read_file$/, '读文件'],
  [/^write_file$/, '写入文件'],
  [/^patch$/, '修改文件'],
  [/^search_files$/, '搜索文件'],
  [/^terminal$/, '运行命令'],
  [/^process_manage$/, '管理后台进程'],
  // Exact tool names first: generic patterns below would misread them ("spreadsheet" contains "read").
  [/^create_document$/, '生成 Word 文档'],
  [/^create_spreadsheet$/, '生成 Excel 表格'],
  [/^create_presentation$/, '生成演示文稿'],
  [/^read_office$/, '读取文档'],
  [/^run_checks$/, '运行检查'],
  [/^delegate_parallel$/, '分派并行任务'],
  [/^delegate_task$/, '分派子任务'],
  [/^external:/, '外部 Agent'],
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
    case 'run_checks':
      return { verb: '运行检查', target: ({ lint: '代码检查', typecheck: '类型检查', test: '测试', all: '全部' } as Record<string, string>)[action ?? str(a.kind) ?? ''] ?? str(a.kind) };
    case 'delegate_parallel':
      return { verb: '分派并行任务', target: Array.isArray(a.tasks) ? `${a.tasks.length} 个` : undefined };
    default: {
      if (name.startsWith('external:')) return { verb: '外部 Agent', target: [name.slice(9), pickTarget(args)].filter(Boolean).join(' · ').slice(0, 120) };
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
        if (typeof data.content === 'string' && data.content) {
          // The trust question is asked before the run starts; once the request shows up, put it back under it.
          const early = items.length && items[items.length - 1].kind === 'trust' ? items.pop() : undefined;
          const asked = splitMoa(data.content);
          items.push({ kind: 'user', id: event.id, content: asked.text, ...(asked.moa ? { moa: true } : {}) });
          if (early) items.push(early);
        }
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
        if (typeof data.full_output_path === 'string') step.fullOutputPath = data.full_output_path;
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
      case 'subtask.started': {
        const id = String(data.subtask_id ?? event.id);
        const worker = typeof data.index === 'number' ? `并行 Worker ${data.index + 1}` : '';
        const step: Step = { id: event.id, verb: worker || '子任务', target: String(data.title || data.goal || '').slice(0, 120), state: 'running', startedAt: event.timestamp, output: '', subtaskId: id,
          input: [data.backend && `执行者：${String(data.backend)}`, data.goal && `目标：${String(data.goal)}`].filter(Boolean).join('\n'),
          agent: {
            type: typeof data.agent === 'string' ? data.agent : undefined, model: typeof data.model === 'string' && data.model ? data.model : undefined,
            background: data.background === true, depth: typeof data.depth === 'number' ? data.depth : undefined,
            recipe: typeof data.recipe_id === 'string' && data.recipe_id ? data.recipe_id : undefined,
          } };
        byExecution.set(`subtask:${id}`, step);
        closeReply();
        stepsBlock(event.id).steps.push(step);
        break;
      }
      case 'subtask.progress':
      case 'subtask.output': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (step) step.output += `${String(data.text ?? '')}\n`;
        break;
      }
      case 'subtask.completed': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (!step) break;
        step.state = data.status === 'failed' ? 'failed' : data.status === 'cancelled' ? 'cancelled' : 'done';
        step.endedAt = event.timestamp;
        step.result = text(data.summary);
        break;
      }
      case 'subtask.steered': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (step) step.steers = [...(step.steers ?? []), String(data.text ?? '')];
        break;
      }
      case 'subtask.steer_rejected': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (step) step.note = '补充要求没有送到：这个子任务已经结束了。';
        break;
      }
      case 'subtask.background_completed':
        closeReply(); closeBlocks();
        items.push({ kind: 'background', id: event.id, summary: String(data.summary ?? '') });
        break;
      case 'moa.references': {
        const references = Array.isArray(data.references) ? data.references as Array<Record<string, unknown>> : [];
        closeReply(); closeBlocks();
        items.push({ kind: 'moa', id: event.id, latencyMs: Number(data.latency_ms ?? 0),
          references: references.map((item) => ({ model: String(item.model ?? ''), text: String(item.text ?? '') })) });
        break;
      }
      case 'subtask.group_completed': {
        const results = Array.isArray(data.results) ? data.results as Array<Record<string, unknown>> : [];
        closeReply(); closeBlocks();
        items.push({ kind: 'group', id: event.id, summary: String(data.summary ?? ''), results: results.map((item, index) => ({
          index: typeof item.index === 'number' ? item.index : index, title: String(item.title ?? ''), status: String(item.status ?? ''),
          summary: String(item.summary ?? ''), changed_files: Array.isArray(item.changed_files) ? item.changed_files.map(String) : [],
          verified: typeof item.verified === 'boolean' ? item.verified : undefined,
          verifier_note: typeof item.verifier_note === 'string' && item.verifier_note ? item.verifier_note : undefined,
        })) });
        break;
      }
      case 'check.results': {
        closeReply(); closeBlocks();
        items.push({ kind: 'checks', id: event.id, results: {
          kind: String(data.kind ?? ''), tool: String(data.tool ?? ''), passed: Number(data.passed ?? 0), failed: Number(data.failed ?? 0),
          skipped: Number(data.skipped ?? 0), duration_ms: typeof data.duration_ms === 'number' ? data.duration_ms : undefined,
          items: Array.isArray(data.items) ? data.items as CheckResults['items'] : [],
        } });
        break;
      }
      case 'run.model_switched': {
        closeReply(); closeBlocks();
        const reason = String(data.reason ?? '').trim();
        items.push({ kind: 'notice', id: event.id, tone: 'switch',
          text: `${String(data.from ?? '当前模型')} 暂时用不了${reason ? `（${reason}）` : ''}，已换成 ${String(data.to ?? '备用模型')} 继续` });
        break;
      }
      case 'run.verify_nudge': {
        closeReply(); closeBlocks();
        const paths = Array.isArray(data.changed_paths) ? data.changed_paths.map((path) => shortPath(String(path))) : [];
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: `改了代码还没验证${paths.length ? `（${paths.slice(0, 3).join('、')}${paths.length > 3 ? ` 等 ${paths.length} 个文件` : ''}）` : ''}，Atlas 先去验证一下` });
        break;
      }
      case 'process.notification': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: data.reason === 'heartbeat' ? '后台进程仍在运行。' : `后台进程输出提醒：${String(data.text ?? '')}` });
        break;
      }
      case 'process.completed': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: `后台进程已结束${data.name ? `：${String(data.name)}` : ''}${typeof data.exit_code === 'number' ? `（退出码 ${data.exit_code}）` : ''}` });
        break;
      }
      case 'run.compaction.progress': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: `正在整理对话上下文${typeof data.percent === 'number' ? `（${Math.max(0, Math.min(100, data.percent))}%）` : ''}` });
        break;
      }
      case 'run.recovery.notice': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'switch',
          text: String(data.message ?? data.detail ?? '模型遇到问题，正在尝试恢复并继续。') });
        break;
      }
      case 'rules.trust_required':
        closeReply(); closeBlocks();
        items.push({ kind: 'trust', id: event.id, event });
        break;
      case 'hook.ran': {
        const failed = typeof data.exit_code === 'number' && data.exit_code !== 0;
        stepsBlock(event.id).steps.push({
          id: event.id, verb: data.exit_code === 2 ? 'Hook 拦下了这一步' : '运行 Hook', target: `${String(data.hook_id ?? '')} · ${String(data.event ?? '')}`,
          state: failed ? 'failed' : 'done', startedAt: event.timestamp, endedAt: event.timestamp,
          result: `退出码 ${String(data.exit_code ?? '?')}，用时 ${String(data.duration_ms ?? '?')} ms`, output: String(data.output ?? ''),
        });
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

/** Share of input tokens served from the provider's prompt cache, e.g. "缓存 62%"; null when unknown or zero. */
export function cacheShare(usage?: RunUsage): string | null {
  const input = usage?.input_tokens ?? 0;
  const cached = usage?.cached_input_tokens ?? 0;
  if (!input || !cached) return null;
  return `缓存 ${Math.round((cached / input) * 100)}%`;
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
