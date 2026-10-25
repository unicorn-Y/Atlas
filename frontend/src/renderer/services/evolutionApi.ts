/** Typed client for the 自动追新 backend (GET/POST/DELETE /api/evolution/*).
 * Follows the same fetch style as services/skillsMarketApi.ts: tolerant
 * normalization (backend may wrap lists or omit optional fields), Chinese
 * offline errors, and an injectable fetcher so tests can stub responses.
 * Shapes mirror core/atlas/api/evolution_router.py + atlas/evolution/*. */

export type EvolutionSourceKind = 'commit' | 'tag' | 'release';

export type EvolutionSourceState = {
  last_id?: string | null;
  last_checked_at?: string | null;
  last_ok_at?: string | null;
};

export type EvolutionSource = {
  id: string;
  repo: string;
  kind: EvolutionSourceKind | string;
  ref?: string | null;
  remote?: string | null;
  last_checked: string | null;
  latest_version: string | null;
  latest_date: string | null;
  cached_entries: number;
};

/** POST /api/evolution/check 的汇总（兼容 {checked,new_commits,new_diffs} 与 watcher.run_check 的 results 形状）。 */
export type EvolutionCheckResult = {
  checked: number;
  ok: boolean;
  new_commits: number;
  new_diffs: number;
  errors: string[];
  checked_at: string | null;
};

export type DiffClass = 'NEW' | 'BETTER_THAN_ATLAS' | 'ALREADY_HAVE' | 'REGRESSION_REMOVED' | 'IRRELEVANT';

export type EvolutionDiff = {
  source: string;
  repo: string | null;
  entry_id: string | null;
  kind: string | null;
  title: string;
  published_at: string | null;
  capabilities: string[];
  cls: DiffClass;
  evidence: string;
  advisory: boolean;
  matched_files: string[];
};

export type ParitySuggestion = 'KEEP' | 'UPGRADE' | 'REPLACE';

export type ParityRow = {
  capability: string;
  capability_id: string | null;
  source: string;
  repo: string | null;
  repo_file: string;
  why_stronger: string;
  atlas_impl: string;
  suggestion: ParitySuggestion;
  advisory: boolean;
};

export type EvolutionDraft = {
  id: string;
  title: string;
  created: string | null;
  path: string;
  source_repo: string;
  atlas_integration_point: string;
  acceptance: string;
  status: string;
  suggestion: ParitySuggestion | string | null;
  branch: string | null;
  exists: boolean;
};

/** POST /api/evolution/drafts/{id}/approve：后端用 200 + ok:false 表达「优雅跳过」，不抛错。 */
export type DraftApproveResult = {
  ok: boolean;
  branch: string | null;
  worktree: string | null;
  status: string | null;
  merge_proposal: string | null;
  reason: string;
};

export type EvolutionBranch = {
  name: string;
  status: string;
  proposal_path: string;
  worktree: string | null;
  base: string | null;
  created_at: string | null;
  draft_id: string | null;
};

export type SkillCandidate = {
  id: string;
  title: string;
  origin: string;
  preview_md: string;
  status: string;
  description: string;
  references: string[];
  source_runs: string[];
};

/** Minimal fetch shape so tests (and callers) can inject a stub fetcher. */
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** Backend answered with a non-2xx; status lets callers special-case 400/404. */
export class EvolutionApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'EvolutionApiError';
    this.status = status;
  }
}

export function isEvolutionApiError(value: unknown): value is EvolutionApiError {
  return value instanceof EvolutionApiError;
}

async function request<T>(apiBaseUrl: string, path: string, init?: RequestInit & { json?: unknown }, fetcher: FetchLike = fetch): Promise<T> {
  const { json, ...rest } = init ?? {};
  let response: Response;
  try {
    response = await fetcher(`${apiBaseUrl}${path}`, {
      ...rest,
      headers: json === undefined ? rest.headers : { 'Content-Type': 'application/json', ...rest.headers },
      body: json === undefined ? rest.body : JSON.stringify(json),
    });
  } catch (cause) {
    // 断网或后端没启动时 fetch 抛英文 TypeError；换成用户能读懂的一句话。
    const error = new Error('连接不上自动追新服务，请确认 Atlas 后端已启动后重试。');
    (error as Error & { cause?: unknown }).cause = cause;
    throw error;
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json() as { error?: unknown; detail?: unknown };
      detail = typeof body.detail === 'string' ? body.detail
        : typeof body.error === 'string' ? body.error
        : JSON.stringify(body.detail ?? body.error ?? body);
    } catch { /* 非 JSON 错误体，忽略 */ }
    throw new EvolutionApiError(response.status, detail ? `HTTP ${response.status}：${detail}` : `自动追新服务返回了 HTTP ${response.status}，请稍后重试。`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const str = (value: unknown, fallback = ''): string => typeof value === 'string' ? value : fallback;
const numOrZero = (value: unknown): number => typeof value === 'number' && Number.isFinite(value) ? value : 0;
const strList = (value: unknown): string[] => Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
/** 取第一个非空字符串字段（兼容后端两种命名，如 file/path、created_at/created）。 */
function firstStr(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value;
  }
  return '';
}

function unwrapList(raw: unknown, keys: string[]): unknown[] {
  if (Array.isArray(raw)) return raw;
  if (isRecord(raw)) {
    for (const key of keys) {
      if (Array.isArray(raw[key])) return raw[key] as unknown[];
    }
  }
  return [];
}

function normalizeSource(raw: unknown, fallbackIndex: number): EvolutionSource {
  const item = isRecord(raw) ? raw : {};
  const state = isRecord(item.state) ? item.state : {};
  const kind = str(item.kind, 'commit').toLowerCase();
  return {
    id: str(item.id, `source-${fallbackIndex}`),
    repo: str(item.repo, str(item.id, '未知仓库')),
    kind: (['commit', 'tag', 'release'] as const).includes(kind as EvolutionSourceKind) ? kind : str(kind, 'commit'),
    ref: typeof item.ref === 'string' ? item.ref : null,
    remote: typeof item.remote === 'string' ? item.remote : null,
    last_checked: firstStr(item, ['last_checked', 'last_checked_at']) || firstStr(state, ['last_checked_at']) || null,
    latest_version: firstStr(item, ['latest_version']) || firstStr(state, ['last_id']) || null,
    latest_date: firstStr(item, ['latest_date']) || firstStr(state, ['last_ok_at']) || null,
    cached_entries: numOrZero(item.cached_entries),
  };
}

function normalizeCheck(raw: unknown): EvolutionCheckResult {
  const item = isRecord(raw) ? raw : {};
  const results = Array.isArray(item.results) ? item.results : [];
  const failed = results.filter((entry): entry is Record<string, unknown> => isRecord(entry) && entry.ok === false);
  return {
    checked: numOrZero(item.checked) || results.length,
    ok: item.ok === undefined ? failed.length === 0 : item.ok === true,
    new_commits: numOrZero(item.new_commits)
      || results.reduce((sum, entry) => sum + (isRecord(entry) ? numOrZero(entry.new_entries) : 0), 0),
    new_diffs: numOrZero(item.new_diffs),
    errors: Array.isArray(item.errors)
      ? item.errors.filter((entry): entry is string => typeof entry === 'string' && entry.trim().length > 0)
      : failed.map((entry) => str(entry.error, '其中一个来源读取失败')),
    checked_at: firstStr(item, ['checked_at']) || null,
  };
}

function normalizeDiff(raw: unknown): EvolutionDiff {
  const item = isRecord(raw) ? raw : {};
  const classes: DiffClass[] = ['NEW', 'BETTER_THAN_ATLAS', 'ALREADY_HAVE', 'REGRESSION_REMOVED', 'IRRELEVANT'];
  const cls = str(item.cls, str(item.classification, 'IRRELEVANT')) as DiffClass;
  const capabilities = strList(item.capabilities).map((entry) => entry);
  return {
    source: str(item.source, str(item.repo, '未知来源')),
    repo: typeof item.repo === 'string' ? item.repo : null,
    entry_id: typeof item.entry_id === 'string' ? item.entry_id : null,
    kind: typeof item.kind === 'string' ? item.kind : null,
    title: firstStr(item, ['title', 'subject']) || '（无标题更新）',
    published_at: typeof item.published_at === 'string' ? item.published_at : null,
    capabilities,
    cls: classes.includes(cls) ? cls : 'IRRELEVANT',
    evidence: firstStr(item, ['evidence', 'reason']),
    advisory: item.advisory === undefined ? true : item.advisory === true,
    matched_files: strList(item.matched_files),
  };
}

function normalizeParityRow(raw: unknown, fallbackIndex: number): ParityRow {
  const item = isRecord(raw) ? raw : {};
  const suggestion = str(item.suggestion, 'KEEP').toUpperCase();
  return {
    capability: str(item.capability, str(item.capability_id, `能力-${fallbackIndex}`)),
    capability_id: typeof item.capability_id === 'string' ? item.capability_id : null,
    source: str(item.source, str(item.repo, '未知来源')),
    repo: typeof item.repo === 'string' ? item.repo : null,
    repo_file: str(item.repo_file),
    why_stronger: str(item.why_stronger),
    atlas_impl: firstStr(item, ['atlas_impl', 'atlas_implementation']),
    suggestion: suggestion === 'UPGRADE' || suggestion === 'REPLACE' ? suggestion : 'KEEP',
    advisory: item.advisory === undefined ? true : item.advisory === true,
  };
}

function normalizeDraft(raw: unknown, fallbackIndex: number): EvolutionDraft {
  const item = isRecord(raw) ? raw : {};
  return {
    id: str(item.id, `draft-${fallbackIndex}`),
    title: firstStr(item, ['title']) || str(item.capability, str(item.id, `任务书-${fallbackIndex}`)),
    created: firstStr(item, ['created', 'created_at']) || null,
    path: firstStr(item, ['path', 'file']),
    source_repo: firstStr(item, ['source_repo', 'repo']) || str(item.source, '未知来源'),
    atlas_integration_point: firstStr(item, ['atlas_integration_point', 'atlas_implementation']),
    acceptance: firstStr(item, ['acceptance', 'why_stronger']),
    status: str(item.status, 'draft'),
    suggestion: typeof item.suggestion === 'string' ? item.suggestion : null,
    branch: typeof item.branch === 'string' ? item.branch : null,
    exists: item.exists === true,
  };
}

function normalizeApprove(raw: unknown): DraftApproveResult {
  const item = isRecord(raw) ? raw : {};
  return {
    ok: item.ok === true,
    branch: firstStr(item, ['branch']) || null,
    worktree: firstStr(item, ['worktree']) || null,
    status: firstStr(item, ['status']) || null,
    merge_proposal: firstStr(item, ['merge_proposal', 'proposal_path']) || null,
    reason: str(item.reason),
  };
}

function normalizeBranch(raw: unknown, fallbackIndex: number): EvolutionBranch {
  const item = isRecord(raw) ? raw : {};
  return {
    name: firstStr(item, ['name', 'branch']) || str(item.id, `branch-${fallbackIndex}`),
    status: str(item.status, 'proposal'),
    proposal_path: firstStr(item, ['proposal_path', 'merge_proposal']),
    worktree: firstStr(item, ['worktree']) || null,
    base: firstStr(item, ['base']) || null,
    created_at: firstStr(item, ['created_at', 'created']) || null,
    draft_id: typeof item.draft_id === 'string' ? item.draft_id : null,
  };
}

/** 候选没有 preview_md 时，用描述 + 参考资料拼一份可读预览。 */
export function buildCandidatePreview(record: Record<string, unknown>): string {
  const lines: string[] = [];
  const description = str(record.description);
  if (description) lines.push(description, '');
  const references = strList(record.references);
  if (references.length) lines.push(`参考资料：${references.join('、')}`, '');
  const parameters = isRecord(record.parameters) ? record.parameters : {};
  const paramKeys = Object.keys(parameters);
  if (paramKeys.length) lines.push(`参数：${paramKeys.map((key) => String(parameters[key])).join('、')}`, '');
  const assets = strList(record.assets);
  if (assets.length) lines.push(`附带文件：${assets.join('、')}`);
  return lines.join('\n').trim();
}

function normalizeCandidate(raw: unknown, fallbackIndex: number): SkillCandidate {
  const item = isRecord(raw) ? raw : {};
  const preview = firstStr(item, ['preview_md', 'preview']);
  return {
    id: str(item.id, `candidate-${fallbackIndex}`),
    title: firstStr(item, ['title', 'display_title']) || str(item.name, str(item.id, `候选技能-${fallbackIndex}`)),
    origin: str(item.origin, 'user_request'),
    preview_md: preview || buildCandidatePreview(item),
    status: str(item.status, 'candidate'),
    description: str(item.description),
    references: strList(item.references),
    source_runs: strList(item.source_runs),
  };
}

// ---------------------------------------------------------------------------
// 端点封装
// ---------------------------------------------------------------------------

export async function listEvolutionSources(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<EvolutionSource[]> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/sources', undefined, fetcher);
  return unwrapList(raw, ['sources']).map(normalizeSource);
}

export async function addEvolutionSource(apiBaseUrl: string, source: { repo: string; kind: EvolutionSourceKind }, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, '/api/evolution/sources', { method: 'POST', json: source }, fetcher);
}

export async function removeEvolutionSource(apiBaseUrl: string, id: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, `/api/evolution/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }, fetcher);
}

export async function runEvolutionCheck(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<EvolutionCheckResult> {
  return normalizeCheck(await request<unknown>(apiBaseUrl, '/api/evolution/check', { method: 'POST', json: {} }, fetcher));
}

export async function listEvolutionDiffs(apiBaseUrl: string, options: { includeIrrelevant?: boolean } = {}, fetcher: FetchLike = fetch): Promise<{ diffs: EvolutionDiff[]; counts: Record<string, number> }> {
  const suffix = options.includeIrrelevant ? '?include_irrelevant=true' : '';
  const raw = await request<unknown>(apiBaseUrl, `/api/evolution/diffs${suffix}`, undefined, fetcher);
  const item = isRecord(raw) ? raw : {};
  const counts: Record<string, number> = {};
  if (isRecord(item.counts)) {
    for (const [key, value] of Object.entries(item.counts)) {
      if (typeof value === 'number' && Number.isFinite(value)) counts[key] = value;
    }
  }
  return { diffs: unwrapList(raw, ['diffs']).map(normalizeDiff), counts };
}

export async function listParityRows(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<{ rows: ParityRow[]; patch_proposal: string }> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/parity', undefined, fetcher);
  const item = isRecord(raw) ? raw : {};
  return {
    rows: unwrapList(raw, ['rows']).map(normalizeParityRow),
    patch_proposal: typeof item.patch_proposal === 'string' ? item.patch_proposal : '',
  };
}

export async function listDrafts(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<EvolutionDraft[]> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/drafts', undefined, fetcher);
  return unwrapList(raw, ['drafts']).map(normalizeDraft);
}

/** 按当前建议生成任务书草稿（UPGRADE/REPLACE 各一份）。返回新建数量。 */
export async function generateDrafts(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<number> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/drafts/generate', { method: 'POST', json: {} }, fetcher);
  const item = isRecord(raw) ? raw : {};
  return Array.isArray(item.created) ? item.created.length : 0;
}

export async function approveDraft(apiBaseUrl: string, draftId: string, base?: string, fetcher: FetchLike = fetch): Promise<DraftApproveResult> {
  const raw = await request<unknown>(apiBaseUrl, `/api/evolution/drafts/${encodeURIComponent(draftId)}/approve`, {
    method: 'POST',
    json: base?.trim() ? { base: base.trim() } : {},
  }, fetcher);
  return normalizeApprove(raw);
}

export async function listBranches(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<{ branches: EvolutionBranch[]; note: string }> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/branches', undefined, fetcher);
  const item = isRecord(raw) ? raw : {};
  return {
    branches: unwrapList(raw, ['branches']).map(normalizeBranch),
    note: typeof item.note === 'string' ? item.note : '合并永远需要人工执行 MERGE-PROPOSAL.md 中的命令',
  };
}

export async function listCandidates(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<SkillCandidate[]> {
  const raw = await request<unknown>(apiBaseUrl, '/api/evolution/candidates', undefined, fetcher);
  return unwrapList(raw, ['candidates']).map(normalizeCandidate);
}

export async function approveCandidate(apiBaseUrl: string, candidateId: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, `/api/evolution/candidates/${encodeURIComponent(candidateId)}/approve`, { method: 'POST', json: {} }, fetcher);
}

export async function rollbackCandidate(apiBaseUrl: string, candidateId: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, `/api/evolution/candidates/${encodeURIComponent(candidateId)}/rollback`, { method: 'POST', json: {} }, fetcher);
}

// ---------------------------------------------------------------------------
// 徽标文案（组件与测试共用）
// ---------------------------------------------------------------------------

/** 差异分类 → 中文徽标。 */
export const DIFF_CLASS_LABEL: Record<DiffClass, string> = {
  NEW: '新能力',
  BETTER_THAN_ATLAS: '上游更强',
  ALREADY_HAVE: '已具备',
  REGRESSION_REMOVED: '上游移除',
  IRRELEVANT: '无关',
};

/** 建议动作 → 中文徽标。 */
export const SUGGESTION_LABEL: Record<ParitySuggestion, string> = {
  KEEP: '保持现状',
  UPGRADE: '建议升级',
  REPLACE: '建议替换',
};

/** 来源类型 → 中文。 */
export const EVOLUTION_KIND_LABEL: Record<EvolutionSourceKind, string> = {
  commit: '提交',
  tag: '标签',
  release: '版本发布',
};

/** 候选来源 → 中文（未知值原样展示）。 */
export function candidateOriginLabel(origin: string): string {
  const known: Record<string, string> = {
    successful_run: '成功会话', user_request: '用户请求', from_runs: '运行沉淀', from_recording: '录制沉淀', upstream: '上游启发',
  };
  return known[origin] ?? origin;
}
