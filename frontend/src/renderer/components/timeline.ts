import type { CheckResults } from '@atlas/backend-adapter';
import type { AgentEvent } from '../../types/runtime';
import { structuredComponent, type StructuredComponentItem } from './StructuredComponentCard';
import { isTodoEdit, parseTodoEdit } from './runInsights';

/** One line for a todo edit the user handed to the Agent. */
export function todoEditNotice(content: string): string {
  const items = parseTodoEdit(content);
  const done = items.filter((item) => item.status === 'completed').length;
  return items.length ? `你调整了待办清单（${items.length} 项，已完成 ${done} 项），Atlas 会按新清单继续` : '你调整了待办清单';
}

/**
 * Turns the raw runtime event stream into what a person wants to read:
 * their message, the steps Atlas took (in plain words), approvals, the reply, and the outcome.
 * Internal bookkeeping events (status, phase, plan) never reach the thread.
 */

export type StepState = 'running' | 'done' | 'failed' | 'cancelled';

export type ToolCategory =
  | 'file-read' | 'file-write' | 'file-edit' | 'file-patch'
  | 'shell' | 'exec' | 'search' | 'todo' | 'plan' | 'question' | 'agent'
  | 'browser' | 'computer' | 'git' | 'process' | 'web' | 'checks' | 'image' | 'memory' | 'other';

export interface Step {
  id: string;
  toolName: string;
  category: ToolCategory;
  verb: string;
  target?: string;
  state: StepState;
  startedAt: string;
  endedAt?: string;
  /** Short human-readable result, separate from the expandable raw payload. */
  summary?: string;
  /** Failure detail promoted from the tool response so it is visible without opening raw details. */
  failureReason?: string;
  input?: string;
  result?: string;
  imagePreview?: string;
  output: string;
  /** Set for delegated sub-agents, which can be cancelled on their own. */
  subtaskId?: string;
  /** Where the backend saved a tool result too large for the model's context. */
  fullOutputPath?: string;
}

export interface RunUsage { input_tokens?: number | null; output_tokens?: number | null; cached_input_tokens?: number | null; context_tokens?: number | null; context_limit?: number | null }
export interface RunChanges { files: number; additions: number; deletions: number }

/** lsp.diagnostics 里的一条诊断；后端最多带 20 条，超出时 count 仍是真实总数。 */
export interface LspDiagnosticItem {
  line: number;
  column?: number;
  severity: 'error' | 'warning' | 'information' | 'hint';
  code?: string;
  message: string;
}

/** review.findings 里的一条发现；line 为 1 起始行号或 null。 */
export interface ReviewFinding {
  file: string;
  line: number | null;
  range: number[] | null;
  severity: 'blocker' | 'major' | 'minor';
  title: string;
  explanation: string;
  evidence: string;
  suggested_fix: string;
}

export type TimelineItem =
  | { kind: 'user'; id: string; content: string; steered?: boolean; timestamp?: string }
  | { kind: 'reply'; id: string; content: string; streaming: boolean; status?: string; timestamp?: string }
  /** Text explicitly delivered by the runtime as run.status with status=reasoning. */
  | { kind: 'reasoning'; id: string; text: string; eventCount: number; truncated: boolean; source: 'run.status' | 'history'; startedAt?: string; endedAt?: string }
  | { kind: 'steps'; id: string; steps: Step[] }
  | { kind: 'approval'; id: string; event: AgentEvent }
  | { kind: 'question'; id: string; event: AgentEvent }
  | { kind: 'plan'; id: string; event: AgentEvent }
  | { kind: 'trust'; id: string; event: AgentEvent }
  /** X2：电脑操控要动你正在用的前台窗口，需要你批准（computer.foreground_required）。 */
  | { kind: 'foreground'; id: string; event: AgentEvent }
  /** X2：浏览器代理卡住要把这一步交还给人（browser.handoff_required）。 */
  | { kind: 'handoff'; id: string; event: AgentEvent }
  | { kind: 'group'; id: string; summary: string; results: Array<{ index: number; title: string; status: string; accepted?: boolean; verification_status?: string; verifier_note?: string; summary: string; changed_files: string[] }> }
  | { kind: 'checks'; id: string; results: CheckResults }
  | { kind: 'cancelled'; id: string; reason?: string }
  /** One-line runtime notes: the model was swapped after errors, or Atlas went back to verify its edits. */
  | { kind: 'notice'; id: string; tone: 'switch' | 'verify' | 'todo' | 'goal'; text: string }
  /** LSP 在编辑后报的新问题：默认收成一行，可展开看明细。 */
  | { kind: 'lsp'; id: string; path: string; count: number; diagnostics: LspDiagnosticItem[] }
  /** /review 代码审查的结构化结论，由 ReviewFindingsCard 渲染；findings 为空即「没有发现问题」。 */
  | { kind: 'review'; id: string; scope: string; scopeLabel: string; workspace: string; mode?: 'general' | 'security' | 'cleanup-only'; findings: ReviewFinding[] }
  | { kind: 'component'; id: string; component: StructuredComponentItem }
  /** Node supplied by a registered client extension renderer. */
  | { kind: 'extension'; id: string; nodeType: string; data: Record<string, unknown> }
  | { kind: 'artifact'; id: string; name: string; summary: string }
  | { kind: 'done'; id: string; result: string; startedAt?: string; endedAt: string; usage?: RunUsage; changes?: RunChanges }
  | { kind: 'failed'; id: string; detail: string; service?: string; reason?: string; retryAfterSeconds?: number; status?: number };

/** A question explicitly tagged for plan review uses the plan approval controls. */
export function isPlanReviewIntent(event: AgentEvent): boolean {
  return event.data.intent === 'plan-review' && event.data.proposal !== true;
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
  [/^deep_research$/, '深度调研'],
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
  list: '查看目录', glob: '查找文件', search: '搜索文件内容', stat: '查看文件信息', edit: '修改', patch: '应用补丁',
};
const PROCESS_ACTIONS: Record<string, string> = {
  start: '启动进程', status: '查看进程状态', read: '读取进程输出', wait: '等待进程结束', cancel: '停止进程', list: '查看进程列表',
};
const GIT_ACTIONS: Record<string, string> = {
  status: '查看 Git 状态', diff: '查看改动', log: '查看提交记录', branch: '查看分支', add: '暂存改动',
  commit: '提交改动', pull: '拉取代码', fetch: '获取远程更新', push: '推送代码',
};

const FILE_ACTION_CATEGORIES: Record<string, ToolCategory> = {
  read: 'file-read', write: 'file-write', append: 'file-write', mkdir: 'file-write',
  copy: 'file-write', move: 'file-write', delete: 'file-write', list: 'file-read',
  glob: 'search', search: 'search', stat: 'file-read', patch: 'file-patch', edit: 'file-edit',
};

const toolString = (value: unknown) => typeof value === 'string' && value.trim() ? value.trim() : undefined;

/** Classify by the public tool identity and its action when available; unknown tools stay safe and legible. */
export function classifyTool(name: string, args: unknown): ToolCategory {
  const input = args && typeof args === 'object' ? args as Record<string, unknown> : {};
  const action = toolString(input.action)?.toLowerCase();
  const key = name.toLowerCase().replace(/[\s./:-]+/g, '_');
  if (key === 'local_file' && action) return FILE_ACTION_CATEGORIES[action] ?? 'other';
  if (key === 'local_edit') return 'file-edit';
  if (key === 'local_shell' || /(^|_)(shell|terminal|bash|powershell|command)(_|$)/.test(key)) return 'shell';
  if (key === 'local_exec' || /(^|_)(exec|exec_command|execute)(_|$)/.test(key)) return 'exec';
  if (/(ask_?user_?question|ask_?question|request_?input|input_?required)/.test(key)) return 'question';
  if (/(exit_?plan|submit_?plan|update_?plan|plan_?mode|\bplan\b)/.test(key)) return 'plan';
  if (/(todo|task_?list|update_?tasks|manage_?tasks)/.test(key)) return 'todo';
  if (/(delegate|subagent|sub_?agent|spawn_?agent|agent_?task|^task$|external_)/.test(key)) return 'agent';
  if (/(apply_?patch|patch_?file|^patch$|multi_?edit)/.test(key)) return 'file-patch';
  if (/(edit_?file|file_?edit|replace_?file|modify_?file|^edit$)/.test(key)) return 'file-edit';
  if (/(write_?file|file_?write|create_?file|save_?file|append_?file|^write$)/.test(key)) return 'file-write';
  if (/(read_?file|file_?read|open_?file|view_?file|^read$)/.test(key)) return 'file-read';
  if (/(search|grep|glob|find_?files?|query_?files?)/.test(key)) return 'search';
  if (/(browser|playwright|webview|navigate|devtools)/.test(key)) return 'browser';
  if (/(computer|screenshot|pywinauto|\bcua\b|click|mouse|keyboard|type_?text)/.test(key)) return 'computer';
  if (/(^|_)git(_|$)/.test(key)) return 'git';
  if (/(process|shell_?session|kill_?shell)/.test(key)) return 'process';
  if (/(web_?search|fetch|http|url|page)/.test(key)) return 'web';
  if (/(run_?checks|lint|type_?check|test_?suite)/.test(key)) return 'checks';
  if (/(image|draw|generate_?image)/.test(key)) return 'image';
  if (/(memory|remember|recall)/.test(key)) return 'memory';
  return 'other';
}

const compact = (value: string, max = 220) => value.replace(/\s+/g, ' ').trim().slice(0, max);

function resultRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function resultMessage(value: unknown): string | undefined {
  const record = resultRecord(value);
  if (!record) return typeof value === 'string' && value.trim() ? compact(value) : undefined;
  for (const key of ['summary', 'text_summary', 'message', 'description', 'error']) {
    const text = toolString(record[key]);
    if (text) return compact(text);
  }
  for (const key of ['matches', 'results', 'items', 'files']) {
    if (Array.isArray(record[key])) return `返回 ${record[key].length} 项`;
  }
  const count = record.count ?? record.total;
  return typeof count === 'number' ? `返回 ${count} 项` : undefined;
}

function summarizeToolResult(category: ToolCategory, value: unknown, execution?: Record<string, unknown>): string | undefined {
  const record = resultRecord(value);
  const explicit = resultMessage(value);
  if (explicit && !(category === 'file-read' && typeof value === 'string')) return explicit;
  if (category === 'file-read' && typeof value === 'string' && value.trim()) return `已读取 ${value.length.toLocaleString()} 个字符`;
  if (category === 'file-read' && typeof record?.content === 'string') return `已读取 ${record.content.length.toLocaleString()} 个字符`;
  if (category === 'search') {
    if (Array.isArray(value)) return `找到 ${value.length} 项`;
    const candidates = [record?.matches, record?.results, record?.items, record?.files].find(Array.isArray);
    if (Array.isArray(candidates)) return `找到 ${candidates.length} 项`;
  }
  const output = toolString(execution?.stdout) ?? toolString(execution?.output);
  if (output) return compact(output);
  if (category.startsWith('file-')) return '文件操作已完成';
  if (category === 'todo') return '待办清单已更新';
  if (category === 'plan') return '计划已更新';
  if (category === 'question') return '已发送问题';
  if (category === 'agent') return '子任务已返回结果';
  if (category === 'checks') return explicit ?? '检查已完成';
  return explicit;
}

function failureMessage(value: unknown, execution: Record<string, unknown> | undefined): string | undefined {
  const result = resultRecord(value);
  const nested = resultRecord(result?.error);
  for (const candidate of [
    toolString(result?.error), toolString(nested?.message), toolString(result?.message), toolString(result?.reason), toolString(result?.detail),
    toolString(execution?.error), toolString(execution?.stderr), typeof value === 'string' ? value : undefined,
  ]) {
    if (candidate) return compact(candidate, 500);
  }
  return undefined;
}

/** Plain-language verb + salient argument for a tool call, e.g. `local_shell {command: "npm test"}` → 运行命令 npm test. */
export function describeTool(name: string, args: unknown): { verb: string; target?: string } {
  let a: Record<string, unknown> = {};
  if (args && typeof args === 'object') {
    a = args as Record<string, unknown>;
  } else if (typeof args === 'string') {
    try {
      const parsed = JSON.parse(args);
      if (parsed && typeof parsed === 'object') a = parsed as Record<string, unknown>;
      else a = { command: args };
    } catch {
      a = { command: args };
    }
  }
  const str = (value: unknown) => typeof value === 'string' && value.trim() ? value.trim() : undefined;
  const action = str(a.action);
  switch (name) {
    case 'local_file':
      return { verb: FILE_ACTIONS[action ?? ''] ?? '处理文件', target: action === 'search' ? str(a.query) ?? str(a.pattern) : str(a.path) && shortPath(str(a.path)!) };
    case 'local_edit':
      return { verb: '修改', target: str(a.path) && shortPath(str(a.path)!) };
    case 'local_shell':
    case 'powershell': {
      const cmd = str(a.command)?.replace(/[\r\n]+/g, ' ').trim();
      return { verb: '运行命令', target: cmd?.slice(0, 120) };
    }
    case 'exec_command': {
      const cmd = str(a.cmd)?.replace(/[\r\n]+/g, ' ').trim();
      return { verb: '运行命令', target: cmd?.slice(0, 120) };
    }
    case 'write_stdin':
      return { verb: a.stop ? '停止进程' : str(a.chars) ? '向进程输入' : '查看进程输出', target: str(a.session_id) };
    case 'local_exec': {
      const cmd = [str(a.executable), ...(Array.isArray(a.args) ? a.args.map(String) : [])].filter(Boolean).join(' ').replace(/[\r\n]+/g, ' ').trim();
      return { verb: '运行', target: cmd.slice(0, 120) || (str(a.stdin)?.replace(/[\r\n]+/g, ' ').slice(0, 80)) };
    }
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

const DIAGNOSTIC_SEVERITIES = ['error', 'warning', 'information', 'hint'] as const;
const FINDING_SEVERITIES = ['blocker', 'major', 'minor'] as const;

/** lsp.diagnostics.data.diagnostics → 逐条规整；非法条目丢弃，最多 20 条。 */
function parseDiagnostics(value: unknown): LspDiagnosticItem[] {
  if (!Array.isArray(value)) return [];
  return value.slice(0, 20).flatMap((item): LspDiagnosticItem[] => {
    if (!item || typeof item !== 'object') return [];
    const record = item as Record<string, unknown>;
    const severity = String(record.severity);
    return [{
      line: Number(record.line ?? 0),
      column: typeof record.column === 'number' ? record.column : undefined,
      severity: (DIAGNOSTIC_SEVERITIES as readonly string[]).includes(severity) ? severity as LspDiagnosticItem['severity'] : 'warning',
      code: typeof record.code === 'string' && record.code ? record.code : undefined,
      message: String(record.message ?? ''),
    }];
  });
}

/** review.findings.data.findings → 逐条规整；非法条目丢弃。 */
function parseFindings(value: unknown): ReviewFinding[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item): ReviewFinding[] => {
    if (!item || typeof item !== 'object') return [];
    const record = item as Record<string, unknown>;
    const severity = String(record.severity);
    return [{
      file: String(record.file ?? ''),
      line: typeof record.line === 'number' ? record.line : null,
      range: Array.isArray(record.range) ? record.range.map(Number) : null,
      severity: (FINDING_SEVERITIES as readonly string[]).includes(severity) ? severity as ReviewFinding['severity'] : 'minor',
      title: String(record.title ?? ''),
      explanation: String(record.explanation ?? ''),
      evidence: String(record.evidence ?? ''),
      suggested_fix: String(record.suggested_fix ?? ''),
    }];
  });
}

/** 步骤详情最多保留的字符数：超长工具输出只留头尾够用的部分，避免大输出撑爆内存和 DOM。 */
const MAX_STEP_TEXT = 4000;
const MAX_REASONING_TEXT = 60_000;
const cap = (value: string) => value.length > MAX_STEP_TEXT
  ? `${value.slice(0, MAX_STEP_TEXT)}\n…（已截断，完整输出共 ${value.length} 个字符）`
  : value;
const appendCapped = (current: string, addition: string) => cap(current + addition);

function imageToolResult(value: unknown): { preview?: string; summary?: string } {
  let result: any = value;
  if (typeof result === 'string') {
    try { result = JSON.parse(result); } catch { return {}; }
  }
  if (!result || typeof result !== 'object' || result._multimodal !== true) return {};
  const content = Array.isArray(result.content) ? result.content : [];
  const part = content.find((item: any) => item && typeof item === 'object' && item.type === 'image_url');
  const url = part?.image_url?.url;
  const preview = typeof url === 'string' && /^data:image\/(png|jpe?g|webp|gif|bmp);base64,/i.test(url) ? url : undefined;
  return { preview, summary: typeof result.text_summary === 'string' ? result.text_summary : undefined };
}

export function buildTimeline(events: AgentEvent[]): TimelineItem[] {
  const items: TimelineItem[] = [];
  const byExecution = new Map<string, Step>();
  let track: { kind: 'steps'; id: string; steps: Step[] } | null = null;
  let reply: { kind: 'reply'; id: string; content: string; streaming: boolean; status?: string; timestamp?: string } | null = null;
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
  // Placeholder rows shown while the model is still streaming a tool call's arguments (tool.preparing).
  // tool.started for the same call takes the row over in place instead of adding a second one.
  const preparing = new Map<string, { step: Step; callId: string; attempt: number; resolved: boolean }>();
  const dropPreparing = (keep?: (entry: { attempt: number }) => boolean) => {
    for (const [key, entry] of preparing) {
      if (entry.resolved || keep?.(entry)) continue;
      for (const item of items) if (item.kind === 'steps') { const at = item.steps.indexOf(entry.step); if (at >= 0) item.steps.splice(at, 1); }
      preparing.delete(key);
    }
  };
  // Once a call has started executing no more argument updates can arrive for it; the next model
  // call reuses the same attempt/index keys.
  const forgetResolved = () => { for (const [key, entry] of preparing) if (entry.resolved) preparing.delete(key); };

  for (const event of events) {
    const data = event.data;
    switch (event.type) {
      case 'run.status': {
        if (data.status !== 'reasoning' || typeof data.text !== 'string' || !data.text) break;
        const previous = items[items.length - 1];
        const snippet = data.text;
        // The kernel streams thinking as raw chunks, so they join without a separator.
        if (previous?.kind === 'reasoning') {
          previous.eventCount += 1;
          previous.endedAt = event.timestamp;
          if (!previous.truncated) {
            const combined = previous.text + snippet;
            previous.truncated = combined.length > MAX_REASONING_TEXT;
            previous.text = combined.slice(0, MAX_REASONING_TEXT);
          }
        } else {
          if (!snippet.trim()) break;
          closeReply(); closeBlocks();
          items.push({ kind: 'reasoning', id: event.id, text: snippet.slice(0, MAX_REASONING_TEXT), eventCount: 1, truncated: snippet.length > MAX_REASONING_TEXT, source: 'run.status', startedAt: event.timestamp, endedAt: event.timestamp });
        }
        break;
      }
      case 'run.started':
        dropPreparing(); forgetResolved();
        runStartedAt = event.timestamp;
        if (typeof data.content === 'string' && data.content) {
          // The trust question is asked before the run starts; once the request shows up, put it back under it.
          const early = items.length && items[items.length - 1].kind === 'trust' ? items.pop() : undefined;
          items.push(isTodoEdit(data.content) ? { kind: 'notice', id: event.id, tone: 'todo', text: todoEditNotice(data.content) } : { kind: 'user', id: event.id, content: data.content, timestamp: event.timestamp });
          if (early) items.push(early);
        }
        closeBlocks(); reply = null; spoken = '';
        // The backend reports loaded rules just before the run starts; show them after the request.
        if (earlyRules) { stepsBlock(earlyRules.id).steps.push(earlyRules); earlyRules = null; }
        break;
      case 'run.background':
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'switch', text: data.background === true ? '当前运行已转入后台，将继续处理并保留审批与通知。' : '当前运行已切回前台。' });
        break;
      case 'tool.preparing': {
        const attempt = Number(data.attempt ?? 1);
        const key = `${attempt}:${String(data.index ?? 0)}`;
        let entry = preparing.get(key);
        if (entry?.resolved) break;
        // A retried model call streams its tool calls again; the earlier attempt's rows are stale.
        dropPreparing((other) => other.attempt >= attempt);
        const toolName = String(data.name ?? '工具');
        const chars = Number(data.chars ?? 0);
        if (!entry) {
          const step: Step = { id: event.id, toolName, category: classifyTool(toolName, {}), verb: describeTool(toolName, {}).verb, state: 'running', startedAt: String(data.started_at ?? event.timestamp), output: '' };
          entry = { step, callId: '', attempt, resolved: false };
          preparing.set(key, entry);
          closeReply();
          stepsBlock(event.id).steps.push(step);
        }
        if (data.tool_call_id) entry.callId = String(data.tool_call_id);
        entry.step.target = `正在生成参数 · ${chars < 1000 ? `${chars} 字` : `${(chars / 1000).toFixed(1)}K 字`}`;
        entry.step.input = typeof data.preview === 'string' && data.preview ? `…${data.preview}` : undefined;
        break;
      }
      case 'tool.started': {
        const key = String(data.tool_call_id || data.call_id || event.id);
        const toolName = String(data.name ?? '工具');
        const args = data.arguments ?? data.input;
        const { verb, target } = describeTool(toolName, args);
        const fields = { toolName, category: classifyTool(toolName, args), verb, target, state: 'running' as const, input: cap(text(args)), output: '' };
        const pending = [...preparing.values()].filter((entry) => !entry.resolved);
        const placeholder = pending.find((entry) => entry.callId && entry.callId === data.tool_call_id)
          ?? pending.find((entry) => !entry.callId && entry.step.toolName === toolName);
        let step: Step;
        if (placeholder) {
          placeholder.resolved = true;
          step = Object.assign(placeholder.step, fields);
        } else {
          step = { id: event.id, startedAt: event.timestamp, ...fields };
          closeReply();
          stepsBlock(event.id).steps.push(step);
        }
        byExecution.set(key, step);
        if (!data.tool_call_id) byExecution.set(`name:${String(data.name)}`, step);
        break;
      }
      case 'tool.completed': {
        forgetResolved();
        const execution = data.execution && typeof data.execution === 'object' ? data.execution as Record<string, unknown> : undefined;
        const key = String(data.tool_call_id || data.call_id || '');
        // A repeated completion for a call that already finished belongs to that row; keep the first result.
        if (key && byExecution.get(key) && byExecution.get(key)!.state !== 'running') break;
        let step = (key && byExecution.get(key)) || byExecution.get(`name:${String(data.name)}`);
        if (!step || step.state !== 'running') {
          const toolName = String(data.name ?? '工具');
          const args = data.arguments ?? execution?.command;
          const { verb, target } = describeTool(toolName, args);
          step = { id: event.id, toolName, category: classifyTool(toolName, args), verb, target, state: 'running', startedAt: event.timestamp, input: cap(text(args)), output: '' };
          stepsBlock(event.id).steps.push(step);
        }
        const result = resultRecord(data.result);
        const failed = Boolean(data.is_error) || result?.is_error === true || execution?.state === 'failed' || execution?.state === 'error'
          || data.status === 'failed' || (typeof execution?.exit_code === 'number' && execution.exit_code !== 0);
        step.state = execution?.state === 'cancelled' ? 'cancelled' : failed ? 'failed' : 'done';
        step.endedAt = event.timestamp;
        const image = imageToolResult(data.result);
        step.imagePreview = image.preview;
        step.result = image.summary || cap(text(data.result));
        step.summary = step.state === 'failed' ? undefined : summarizeToolResult(step.category, data.result, execution);
        if (step.state === 'failed') step.failureReason = failureMessage(data.result, execution) ?? '工具返回失败状态';
        if (typeof data.full_output_path === 'string') step.fullOutputPath = data.full_output_path;
        if (execution) {
          const parts = [execution.stdout, execution.stderr].map((value) => cap(text(value))).filter(Boolean);
          if (parts.length && !step.output) step.output = parts.join('\n');
        }
        break;
      }
      case 'tool.output': {
        const step = byExecution.get(String(data.tool_call_id ?? '')) ?? byExecution.get(`name:${String(data.name)}`);
        if (step) step.output = appendCapped(step.output, String(data.text ?? ''));
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
      case 'computer.foreground_required':
        closeReply(); closeBlocks();
        items.push({ kind: 'foreground', id: event.id, event });
        break;
      case 'browser.handoff_required':
        closeReply(); closeBlocks();
        items.push({ kind: 'handoff', id: event.id, event });
        break;
      case 'message.delta':
        if (!reply) { reply = { kind: 'reply', id: event.id, content: '', streaming: true, timestamp: event.timestamp }; items.push(reply); closeBlocks(); }
        reply.content += String(data.content ?? '');
        break;
      case 'message.completed': {
        const full = String(data.content ?? reply?.content ?? '');
        const body = spoken && full.startsWith(spoken) ? full.slice(spoken.length).trimStart() : full;
        if (reply) { reply.content = body; reply.streaming = false; }
        else if (body.trim()) items.push({ kind: 'reply', id: event.id, content: body, streaming: false, timestamp: event.timestamp });
        reply = null; closeBlocks();
        break;
      }
      case 'subtask.started': {
        const id = String(data.subtask_id ?? event.id);
        const worker = typeof data.index === 'number' ? `并行 Worker ${data.index + 1}` : '';
        const step: Step = { id: event.id, toolName: 'subtask', category: 'agent', verb: worker || '子任务', target: String(data.title || data.goal || '').slice(0, 120), state: 'running', startedAt: event.timestamp, output: '', subtaskId: id,
          input: [data.backend && `执行者：${String(data.backend)}`, data.goal && `目标：${String(data.goal)}`].filter(Boolean).join('\n') };
        byExecution.set(`subtask:${id}`, step);
        closeReply();
        stepsBlock(event.id).steps.push(step);
        break;
      }
      case 'subtask.progress':
      case 'subtask.output': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (step) step.output = appendCapped(step.output, `${String(data.text ?? '')}\n`);
        break;
      }
      case 'subtask.completed': {
        const step = byExecution.get(`subtask:${String(data.subtask_id ?? '')}`);
        if (!step) break;
        step.state = data.status === 'failed' ? 'failed' : data.status === 'cancelled' ? 'cancelled' : 'done';
        step.endedAt = event.timestamp;
        step.result = cap(text(data.summary));
        step.summary = step.state === 'failed' ? undefined : resultMessage(data.summary) ?? '子任务已完成';
        if (step.state === 'failed') step.failureReason = resultMessage(data.summary) ?? '子任务执行失败';
        break;
      }
      case 'subtask.group_completed': {
        const results = Array.isArray(data.results) ? data.results as Array<Record<string, unknown>> : [];
        closeReply(); closeBlocks();
        items.push({ kind: 'group', id: event.id, summary: String(data.summary ?? ''), results: results.map((item, index) => ({
          index: typeof item.index === 'number' ? item.index : index, title: String(item.title ?? ''), status: String(item.status ?? ''),
          accepted: typeof item.accepted === 'boolean' ? item.accepted : undefined,
          verification_status: typeof item.verification_status === 'string' ? item.verification_status : undefined,
          verifier_note: typeof item.verifier_note === 'string' ? item.verifier_note : undefined,
          summary: String(item.summary ?? ''), changed_files: Array.isArray(item.changed_files) ? item.changed_files.map(String) : [],
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
      case 'mcp.startup.progress': {
        closeReply(); closeBlocks();
        const state = String(data.state ?? '');
        const label = state === 'ready' ? '已就绪' : state === 'failed' ? '启动失败' : '启动中';
        const server = String(data.server ?? 'MCP 服务');
        const message = String(data.message ?? '正在连接');
        items.push({ kind: 'notice', id: event.id, tone: state === 'failed' ? 'verify' : 'switch', text: `${server} · ${label}：${message}` });
        break;
      }
      case 'media.ocr.progress': {
        closeReply(); closeBlocks();
        const state = String(data.state ?? 'downloading');
        const detail = String(data.detail ?? '正在准备本地中英文 OCR');
        const percentage = Math.max(0, Math.min(100, Math.round(Number(data.progress ?? 0) * 100)));
        items.push({ kind: 'notice', id: event.id, tone: state === 'failed' ? 'verify' : 'switch',
          text: state === 'ready' ? `本地 OCR 已就绪：${detail}`
            : state === 'failed' ? `本地 OCR 准备失败：${detail}`
              : `正在准备本地 OCR（${percentage}%）：${detail}` });
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
        const before = typeof data.before_tokens === 'number' ? data.before_tokens.toLocaleString() : '';
        const after = typeof data.after_tokens === 'number' ? data.after_tokens.toLocaleString() : '';
        const duration = typeof data.duration_ms === 'number' ? ` · ${Math.max(0, data.duration_ms)} ms` : '';
        const count = before && after ? `（${before} → ${after} tokens）` : '';
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: `上下文整理完成${count}${duration}` });
        break;
      }
      case 'context.window.switched': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'switch', text: '已切换到新上下文' });
        break;
      }
      case 'run.recovery.notice': {
        closeReply(); closeBlocks();
        // A restart-resumed run was persisted as failed, so replaying it puts a
        // "没能完成" row right here. The run is continuing, not finished: drop
        // that row and let the notice below carry the interruption instead.
        if (data.reason === 'service_restart') {
          while (items.length && items[items.length - 1].kind === 'failed') items.pop();
        }
        items.push({ kind: 'notice', id: event.id, tone: 'switch',
          text: String(data.message ?? data.detail ?? '模型遇到问题，正在尝试恢复并继续。') });
        break;
      }
      // Goal loop: the judge's verdict after a turn, then the hand-off that keeps
      // the run going. Both were emitted since the goal loop landed but the
      // timeline had no case, so every verdict fell through to `default` and the
      // user never learned why Atlas continued (or stopped).
      case 'goal.updated': {
        const message = String(data.message ?? data.reason ?? '').trim();
        if (!message) break;
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: data.verdict === 'blocked' ? 'verify' : 'goal',
          text: data.status === 'done' || data.verdict === 'done' ? `目标已达成：${message}` : message });
        break;
      }
      case 'goal.continuation': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'goal',
          text: `目标还没完成${data.reason ? `（${String(data.reason)}）` : ''}，Atlas 接着做` });
        break;
      }
      // A steer that never reached the run. steer() returns true unconditionally, so
      // without this notice a rejected message would vanish with no feedback at all.
      case 'run.steer.rejected': {
        closeReply(); closeBlocks();
        items.push({ kind: 'notice', id: event.id, tone: 'verify',
          text: data.reason === 'run_not_active' ? '这条消息没送到：任务已经不在运行了'
            : data.reason === 'invalid_content' ? '这条消息没送到：内容是空的'
              : `这条消息没送到${data.reason ? `（${String(data.reason)}）` : ''}` });
        break;
      }
      case 'rules.trust_required':
        closeReply(); closeBlocks();
        items.push({ kind: 'trust', id: event.id, event });
        break;
      case 'hook.ran': {
        const failed = typeof data.exit_code === 'number' && data.exit_code !== 0;
        stepsBlock(event.id).steps.push({
          id: event.id, toolName: 'hook.ran', category: 'other', verb: data.exit_code === 2 ? 'Hook 拦下了这一步' : '运行 Hook', target: `${String(data.hook_id ?? '')} · ${String(data.event ?? '')}`,
          state: failed ? 'failed' : 'done', startedAt: event.timestamp, endedAt: event.timestamp,
          summary: `退出码 ${String(data.exit_code ?? '?')}，用时 ${String(data.duration_ms ?? '?')} ms`,
          ...(failed ? { failureReason: cap(String(data.output ?? 'Hook 执行失败')).slice(0, 500) } : {}),
          result: `退出码 ${String(data.exit_code ?? '?')}，用时 ${String(data.duration_ms ?? '?')} ms`, output: cap(String(data.output ?? '')),
        });
        break;
      }
      case 'run.steered':
        if (data.immediate && reply) reply.status = '被用户打断';
        closeReply(); closeBlocks();
        if (isTodoEdit(String(data.content ?? ''))) items.push({ kind: 'notice', id: event.id, tone: 'todo', text: todoEditNotice(String(data.content ?? '')) });
        else items.push({ kind: 'user', id: event.id, content: String(data.content ?? ''), steered: true });
        break;
      case 'rules.loaded': {
        const files = Array.isArray(data.files) ? data.files as Array<{ path?: string }> : [];
        if (!files.length) break;
        const step: Step = {
          id: event.id, toolName: 'rules.loaded', category: 'file-read', verb: '读取项目规则', target: files.map((file) => shortPath(String(file.path ?? ''))).join('、'),
          state: 'done', startedAt: event.timestamp, endedAt: event.timestamp, summary: `加载了 ${files.length} 个规则文件`, output: '',
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
      case 'lsp.diagnostics': {
        closeReply(); closeBlocks();
        const diagnostics = parseDiagnostics(data.diagnostics);
        const count = typeof data.count === 'number' ? data.count : diagnostics.length;
        if (count <= 0 && !diagnostics.length) break;
        items.push({ kind: 'lsp', id: event.id, path: String(data.path ?? ''), count, diagnostics });
        break;
      }
      case 'review.findings': {
        closeReply(); closeBlocks();
        items.push({
          kind: 'review', id: event.id,
          scope: String(data.scope ?? 'working_tree'),
          mode: data.mode === 'security' || data.mode === 'cleanup-only' ? data.mode : 'general',
          scopeLabel: String(data.scope_label ?? '当前未提交改动'),
          workspace: String(data.workspace ?? ''),
          findings: parseFindings(data.findings),
        });
        break;
      }
      case 'component.push': {
        closeReply(); closeBlocks();
        const component = structuredComponent(event);
        if (!component) break;
        const prior = items.findIndex((item) => item.kind === 'component' && item.component.id === component.id);
        const item = { kind: 'component' as const, id: event.id, component };
        if (prior >= 0) items[prior] = item; else items.push(item);
        break;
      }
      case 'run.completed':
        dropPreparing();
        items.push({
          kind: 'done', id: event.id, result: text(data.result), startedAt: runStartedAt, endedAt: event.timestamp,
          usage: data.usage && typeof data.usage === 'object' ? data.usage as RunUsage : undefined,
          changes: data.changes && typeof data.changes === 'object' ? data.changes as RunChanges : undefined,
        });
        break;
      case 'run.cancelled':
        dropPreparing();
        closeReply();
        items.push({ kind: 'cancelled', id: event.id, reason: text(data.reason) || undefined });
        break;
      case 'run.failed':
        dropPreparing();
        items.push({
          kind: 'failed', id: event.id,
          detail: text(data.detail ?? data.code) || '未知错误',
          service: typeof data.service === 'string' ? data.service : undefined,
          reason: typeof data.reason === 'string' ? data.reason : undefined,
          retryAfterSeconds: typeof data.retry_after_seconds === 'number' ? data.retry_after_seconds : undefined,
          status: typeof data.status === 'number' ? data.status : undefined,
        });
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

/** One stored tool call (assistant metadata.tool_calls entry) as a finished Step; its result is attached later. */
export function historyStep(call: unknown, createdAt: string): Step | null {
  if (!call || typeof call !== 'object') return null;
  const record = call as Record<string, unknown>;
  const fn = record.function && typeof record.function === 'object' ? record.function as Record<string, unknown> : record;
  const name = typeof fn.name === 'string' ? fn.name : '';
  if (!name) return null;
  let args: unknown = fn.arguments;
  if (typeof args === 'string') {
    try { args = JSON.parse(args); } catch { /* keep the raw string */ }
  }
  const { verb, target } = describeTool(name, args);
  return {
    id: String(record.id ?? `${name}-${createdAt}`), toolName: name, category: classifyTool(name, args),
    verb, target, state: 'cancelled', startedAt: createdAt, output: '',
    input: args === undefined ? undefined : text(args),
  };
}

/** Fill a history Step from its stored tool message. */
export function attachHistoryResult(step: Step, content: string, metadata: Record<string, unknown>, createdAt: string) {
  const receipt = typeof metadata.receipt_state === 'string' ? metadata.receipt_state : '';
  step.state = receipt === 'failed' || receipt === 'error' || receipt === 'denied' ? 'failed' : 'done';
  step.result = content;
  step.endedAt = createdAt;
  if (typeof metadata.duration_ms === 'number') step.endedAt = new Date(Date.parse(step.startedAt) + metadata.duration_ms).toISOString();
  if (typeof metadata.output_ref === 'string' && metadata.output_ref) step.fullOutputPath = metadata.output_ref;
  if (step.state === 'failed') step.failureReason = content.split('\n').map((line) => line.trim()).filter(Boolean).pop()?.slice(0, 200);
}
