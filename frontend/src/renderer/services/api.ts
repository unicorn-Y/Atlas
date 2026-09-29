/** Thin JSON fetch helper for backend routes not wrapped by BackendAdapter. */
export async function api<T>(apiBaseUrl: string, path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const { json, ...rest } = init ?? {};
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...rest,
    headers: json === undefined ? rest.headers : { 'Content-Type': 'application/json', ...rest.headers },
    body: json === undefined ? rest.body : JSON.stringify(json),
  });
  if (!response.ok) {
    let detail = '';
    try { const body = await response.json(); detail = typeof body?.detail === 'string' ? body.detail : JSON.stringify(body?.detail ?? body); } catch { /* non-JSON error */ }
    throw new Error(detail ? `HTTP ${response.status}：${detail}` : `HTTP ${response.status}`);
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export function relativeTime(value?: string | null): string {
  if (!value) return '';
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return '';
  const diff = (Date.now() - date.getTime()) / 1000;
  const future = diff < 0;
  const abs = Math.abs(diff);
  const unit = abs < 60 ? '刚刚' : abs < 3600 ? `${Math.round(abs / 60)} 分钟` : abs < 86400 ? `${Math.round(abs / 3600)} 小时` : abs < 86400 * 30 ? `${Math.round(abs / 86400)} 天` : date.toLocaleDateString();
  if (unit === '刚刚' || abs >= 86400 * 30) return unit;
  return future ? `${unit}后` : `${unit}前`;
}
