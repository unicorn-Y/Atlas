/** Typed client for the Skill Market backend (GET/POST/DELETE /api/skills/market/*).
 * Follows the same fetch style as services/api.ts, but keeps the HTTP status so
 * the 409 same-name conflict can drive the overwrite confirm dialog. */

export type MarketSourceKind = 'official' | 'skillssh' | 'clawhub' | 'github' | 'custom';
export type MarketTap = { id: string; kind: MarketSourceKind; url?: string | null; proxy?: string | null };

export type MarketSearchHit = {
  source: string;
  id: string;
  name: string;
  description: string;
  stars: number | null;
  downloads: number | null;
  installed: boolean;
};

export type MarketSkillFile = { path: string };

export type MarketSkillDetail = {
  name: string;
  description: string;
  version: string;
  author: string | null;
  files: MarketSkillFile[];
  skill_md: string;
};

export type SkillUpdate = {
  name: string;
  source: string;
  current_version: string;
  latest_version: string;
  changes?: string | null;
};

/** GET /api/skills 的宽松类型：后端会逐步补 origin_kind / enabled / version，前端缺省渲染。 */
export type InstalledSkillRecord = {
  name: string;
  description?: string;
  category?: string;
  tags?: string[];
  version?: string | null;
  enabled?: boolean;
  origin_kind?: string | null;
  source?: string | null;
};

export type InstallScope = 'user' | 'project';

/** Minimal fetch shape so tests (and callers) can inject a stub fetcher. */
export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

/** Backend answered with a non-2xx; status lets callers special-case 404/409. */
export class MarketApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = 'MarketApiError';
    this.status = status;
  }
}

/** 409：市场里有同名技能，且本地已存在同名的；需要用户确认「覆盖安装」。 */
export class MarketConflictError extends MarketApiError {
  readonly skillName: string;
  constructor(skillName: string, detail?: string) {
    super(409, detail?.trim() || `已有一个同名的技能「${skillName}」，直接安装会互相覆盖。`);
    this.name = 'MarketConflictError';
    this.skillName = skillName;
  }
}

export function isMarketApiError(value: unknown): value is MarketApiError {
  return value instanceof MarketApiError;
}

export function isMarketConflictError(value: unknown): value is MarketConflictError {
  return value instanceof MarketConflictError;
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
    // 断网、代理失败时 fetch 抛的是英文 TypeError；换成用户能读懂的一句话。
    const error = new Error('连接不上技能市场，请检查网络或代理设置后重试。');
    (error as Error & { cause?: unknown }).cause = cause;
    throw error;
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json() as { error?: unknown; detail?: unknown };
      detail = typeof body.error === 'string' ? body.error
        : typeof body.detail === 'string' ? body.detail
        : JSON.stringify(body.error ?? body.detail ?? body);
    } catch { /* 非 JSON 错误体，忽略 */ }
    throw new MarketApiError(response.status, detail ? `HTTP ${response.status}：${detail}` : `技能市场返回了 HTTP ${response.status}，请稍后重试。`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const str = (value: unknown, fallback = ''): string => typeof value === 'string' ? value : fallback;
const num = (value: unknown): number | null => typeof value === 'number' && Number.isFinite(value) ? value : null;
const bool = (value: unknown): boolean => value === true;

function normalizeHit(raw: unknown, fallbackIndex: number): MarketSearchHit {
  const item = isRecord(raw) ? raw : {};
  return {
    source: str(item.source, 'unknown'),
    id: str(item.id, str(item.name, `item-${fallbackIndex}`)),
    name: str(item.name, str(item.id, '未命名技能')),
    description: str(item.description),
    stars: num(item.stars),
    downloads: num(item.downloads),
    installed: bool(item.installed),
  };
}

function normalizeDetail(raw: unknown, hit: MarketSearchHit): MarketSkillDetail {
  const item = isRecord(raw) ? raw : {};
  const rawFiles = Array.isArray(item.files) ? item.files : [];
  return {
    name: str(item.name, hit.name),
    description: str(item.description, hit.description),
    version: str(item.version, '未知版本'),
    author: typeof item.author === 'string' && item.author.trim() ? item.author : null,
    files: rawFiles.map((file, index) => typeof file === 'string' ? { path: file }
      : isRecord(file) ? { path: str(file.path, str(file.name, `file-${index}`)) }
      : { path: `file-${index}` }),
    skill_md: str(item.skill_md, str(item.skillMd)),
  };
}

function normalizeUpdates(raw: unknown): SkillUpdate[] {
  const list = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.updates) ? raw.updates : [];
  return list.map((item, index) => {
    const record = isRecord(item) ? item : {};
    return {
      name: str(record.name, `技能-${index}`),
      source: str(record.source, '未知来源'),
      current_version: str(record.current_version, '?'),
      latest_version: str(record.latest_version, '?'),
      changes: typeof record.changes === 'string' ? record.changes : null,
    };
  });
}

/** 宽松解析 GET /api/skills：接受数组或 {skills|items: [...]}，字段允许缺省。 */
export function normalizeInstalledSkills(raw: unknown): InstalledSkillRecord[] {
  const list = Array.isArray(raw) ? raw
    : isRecord(raw) && Array.isArray(raw.skills) ? raw.skills
    : isRecord(raw) && Array.isArray(raw.items) ? raw.items : [];
  return list.map((item, index) => {
    const record = isRecord(item) ? item : {};
    return {
      name: str(record.name, `未命名技能-${index}`),
      description: str(record.description) || undefined,
      category: str(record.category) || undefined,
      tags: Array.isArray(record.tags) ? record.tags.filter((tag): tag is string => typeof tag === 'string') : undefined,
      version: typeof record.version === 'string' ? record.version : null,
      enabled: typeof record.enabled === 'boolean' ? record.enabled : undefined,
      origin_kind: typeof record.origin_kind === 'string' ? record.origin_kind : null,
      source: typeof record.source === 'string' ? record.source : null,
    };
  });
}

function normalizeTaps(raw: unknown): MarketTap[] {
  const list = Array.isArray(raw) ? raw : isRecord(raw) && Array.isArray(raw.taps) ? raw.taps : [];
  return list.map((item, index) => {
    const record = isRecord(item) ? item : {};
    const kind = str(record.kind, 'custom');
    return {
      id: str(record.id, `tap-${index}`),
      kind: (['official', 'skillssh', 'clawhub', 'github', 'custom'] as const).includes(kind as MarketSourceKind)
        ? kind as MarketSourceKind : 'custom',
      url: typeof record.url === 'string' ? record.url : null,
      proxy: typeof record.proxy === 'string' ? record.proxy : null,
    };
  });
}

export async function searchMarket(apiBaseUrl: string, query: { q?: string; source?: string } = {}, fetcher: FetchLike = fetch): Promise<MarketSearchHit[]> {
  const params = new URLSearchParams();
  if (query.q?.trim()) params.set('q', query.q.trim());
  if (query.source?.trim()) params.set('source', query.source.trim());
  const suffix = params.toString() ? `?${params.toString()}` : '';
  const data = await request<{ results?: unknown[] }>(apiBaseUrl, `/api/skills/market/search${suffix}`, undefined, fetcher);
  // 结果完全无法辨认的条目直接丢弃，占位的卡片对用户没有价值。
  return (Array.isArray(data?.results) ? data.results : []).flatMap((raw, index) => {
    const normalized = isRecord(raw) ? normalizeHit(raw, index) : null;
    return normalized ? [normalized] : [];
  });
}

export async function getMarketSkill(apiBaseUrl: string, source: string, id: string, fetcher: FetchLike = fetch): Promise<MarketSkillDetail> {
  const raw = await request<unknown>(apiBaseUrl, `/api/skills/market/${encodeURIComponent(source)}/${encodeURIComponent(id)}`, undefined, fetcher);
  return normalizeDetail(raw, { source, id, name: id, description: '', stars: null, downloads: null, installed: false });
}

export async function installSkill(apiBaseUrl: string, options: {
  source: string; id: string; scope: InstallScope; overwrite?: boolean;
}, fetcher: FetchLike = fetch): Promise<{ ok: true }> {
  try {
    await request(apiBaseUrl, '/api/skills/market/install', {
      method: 'POST',
      json: { source: options.source, id: options.id, scope: options.scope, ...(options.overwrite ? { overwrite: true } : {}) },
    }, fetcher);
    return { ok: true };
  } catch (cause) {
    if (cause instanceof MarketApiError && cause.status === 409) throw new MarketConflictError(options.id, cause.message);
    throw cause;
  }
}

export async function fetchUpdates(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<SkillUpdate[]> {
  return normalizeUpdates(await request<unknown>(apiBaseUrl, '/api/skills/updates', undefined, fetcher));
}

export async function updateSkill(apiBaseUrl: string, name: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, '/api/skills/market/update', { method: 'POST', json: { name } }, fetcher);
}

export async function updateAllSkills(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, '/api/skills/market/update-all', { method: 'POST', json: {} }, fetcher);
}

export async function uninstallMarketSkill(apiBaseUrl: string, name: string, fetcher: FetchLike = fetch): Promise<void> {
  await request(apiBaseUrl, `/api/skills/market/${encodeURIComponent(name)}`, { method: 'DELETE' }, fetcher);
}

export async function listInstalledSkills(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<InstalledSkillRecord[]> {
  return normalizeInstalledSkills(await request<unknown>(apiBaseUrl, '/api/skills', undefined, fetcher));
}

/** 启用/停用开关。后端还没实现时会 404：返回 false 并保持界面可用（不当作失败）。 */
export async function setSkillEnabled(apiBaseUrl: string, name: string, enabled: boolean, fetcher: FetchLike = fetch): Promise<boolean> {
  try {
    await request(apiBaseUrl, `/api/skills/${encodeURIComponent(name)}/enabled`, { method: 'PATCH', json: { enabled } }, fetcher);
    return true;
  } catch (cause) {
    if (cause instanceof MarketApiError && cause.status === 404) return false;
    throw cause;
  }
}

export async function listMarketSources(apiBaseUrl: string, fetcher: FetchLike = fetch): Promise<MarketTap[]> {
  return normalizeTaps(await request<unknown>(apiBaseUrl, '/api/skills/market/sources', undefined, fetcher));
}

export async function addMarketSource(apiBaseUrl: string, tap: { kind: MarketSourceKind; url?: string; proxy?: string }, fetcher: FetchLike = fetch): Promise<MarketTap[]> {
  return normalizeTaps(await request<unknown>(apiBaseUrl, '/api/skills/market/sources', { method: 'POST', json: tap }, fetcher));
}

export async function removeMarketSource(apiBaseUrl: string, id: string, fetcher: FetchLike = fetch): Promise<MarketTap[]> {
  return normalizeTaps(await request<unknown>(apiBaseUrl, `/api/skills/market/sources/${encodeURIComponent(id)}`, { method: 'DELETE' }, fetcher));
}

/** 来源类型的中文名，卡片、筛选和来源管理共用。 */
export const SOURCE_KIND_LABEL: Record<MarketSourceKind, string> = {
  official: '官方市场', skillssh: 'skills.sh', clawhub: 'ClawHub', github: 'GitHub', custom: '自定义',
};

/** origin_kind → 中文徽标文案（未知值原样展示，缺省按「本地」）。 */
export function originLabel(originKind?: string | null): string {
  const known: Record<string, string> = {
    marketplace: '市场', plugin: '插件', project: '项目', user: '用户',
    local_recorded: '本机录制', local_evolved: '自学候选',
  };
  if (!originKind) return '本地';
  return known[originKind] ?? originKind;
}
