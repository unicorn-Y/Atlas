/** Typed client for 组件追新 (core/atlas/api/upstream_router.py → /api/upstream). */

export type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export type UpstreamStatus = 'latest' | 'outdated' | 'unknown' | 'error' | 'held';
export type UpstreamMode = 'off' | 'check' | 'auto';

export type UpstreamComponent = {
  id: string;
  name: string;
  category: string;
  category_label: string;
  kind: string;
  current: string;
  latest: string;
  status: UpstreamStatus | string;
  strategy: string;
  strategy_label: string;
  spec: string;
  source: string;
  url: string;
  locations: string[];
  note: string;
  detail: Record<string, unknown>;
  actionable: boolean;
  held?: boolean;
  hold_reason?: string;
  failed_latest?: boolean;
  last_failure?: { version: string; reason: string; at: string };
};

export type UpstreamCategory = {
  id: string;
  label: string;
  hint: string;
  total: number;
  outdated: number;
  actionable: number;
};

export type UpstreamSettings = {
  mode: UpstreamMode;
  interval_hours: number;
  push: boolean;
  holds: Record<string, string>;
};

export type UpstreamRunResult = { status: 'applied' | 'failed' | 'skipped' | string; note?: string; reason?: string; version?: string; at?: string };

export type UpstreamRun = {
  id?: string;
  state?: 'running' | 'succeeded' | 'partial' | 'failed' | 'nothing' | 'skipped' | 'cancelled' | 'interrupted' | string;
  phase?: string;
  started_at?: string;
  finished_at?: string | null;
  plan?: string[];
  steps?: { at: string; text: string }[];
  results?: Record<string, UpstreamRunResult>;
  commits?: { group: string; sha: string }[];
  pushed?: boolean;
  restart_required?: boolean;
  warnings?: string[];
  error?: string;
};

export type UpstreamPending = { commit: string; pushed: boolean; at: string; summary: string[] } | null;

export type UpstreamView = {
  checked_at: string | null;
  duration_seconds?: number;
  errors: string[];
  components: UpstreamComponent[];
  summary: { total: number; outdated: number; actionable: number; errors: number; categories: UpstreamCategory[] };
  settings: UpstreamSettings;
  checking: boolean;
  run: UpstreamRun;
  pending: UpstreamPending;
  supported: boolean;
};

async function request<T>(apiBaseUrl: string, path: string, init?: RequestInit & { json?: unknown }, fetcher: FetchLike = fetch): Promise<T> {
  const { json, ...rest } = init ?? {};
  let response: Response;
  try {
    response = await fetcher(`${apiBaseUrl}${path}`, {
      ...rest,
      headers: json === undefined ? rest.headers : { 'Content-Type': 'application/json', ...rest.headers },
      body: json === undefined ? rest.body : JSON.stringify(json),
    });
  } catch {
    throw new Error('连接不上追新服务，请确认 Atlas 后端已启动后重试。');
  }
  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json() as { detail?: unknown };
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail ?? body);
    } catch { /* 非 JSON 错误体 */ }
    throw new Error(detail || `追新服务返回了 HTTP ${response.status}，请稍后重试。`);
  }
  return response.json() as Promise<T>;
}

const enc = (id: string) => id.split('/').map(encodeURIComponent).join('/');

export const getUpstream = (base: string, fetcher?: FetchLike) =>
  request<UpstreamView>(base, '/api/upstream', undefined, fetcher);

export const startUpstreamCheck = (base: string, fetcher?: FetchLike) =>
  request<{ started: boolean }>(base, '/api/upstream/check', { method: 'POST' }, fetcher);

export const applyUpstream = (base: string, body: { ids?: string[]; category?: string }, fetcher?: FetchLike) =>
  request<{ started: boolean; reason?: string; hot?: Record<string, UpstreamRunResult> }>(base, '/api/upstream/apply', { method: 'POST', json: body }, fetcher);

export const cancelUpstreamRun = (base: string, fetcher?: FetchLike) =>
  request<{ cancelled: boolean }>(base, '/api/upstream/run/cancel', { method: 'POST' }, fetcher);

export const saveUpstreamSettings = (base: string, patch: Partial<Pick<UpstreamSettings, 'mode' | 'interval_hours' | 'push'>>, fetcher?: FetchLike) =>
  request<UpstreamSettings>(base, '/api/upstream/settings', { method: 'PUT', json: patch }, fetcher);

export const holdUpstream = (base: string, id: string, reason = '手动锁定', fetcher?: FetchLike) =>
  request<UpstreamSettings>(base, '/api/upstream/holds', { method: 'POST', json: { id, reason } }, fetcher);

export const releaseUpstream = (base: string, id: string, fetcher?: FetchLike) =>
  request<UpstreamSettings>(base, `/api/upstream/holds/${enc(id)}`, { method: 'DELETE' }, fetcher);

export const clearUpstreamFailure = (base: string, id: string, fetcher?: FetchLike) =>
  request<{ ok: boolean }>(base, `/api/upstream/failures/${enc(id)}`, { method: 'DELETE' }, fetcher);

export type UpstreamWatch = { markdown: string; path: string; last_run: number; running: boolean };

export const getUpstreamWatch = (base: string, fetcher?: FetchLike) =>
  request<UpstreamWatch>(base, '/api/upstream/watch', undefined, fetcher);

export const startUpstreamWatch = (base: string, fetcher?: FetchLike) =>
  request<{ started: boolean; running: boolean }>(base, '/api/upstream/watch', { method: 'POST' }, fetcher);
