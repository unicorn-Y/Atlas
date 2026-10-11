/** 技能与工具库后端接口：/api/library/*。 */

export type LibraryKind = 'skill' | 'tool';

export interface LibraryCategory {
  id: string; name: string; description: string; keywords: string[]; builtin: boolean; count: number; created_by?: string;
}

export interface LibraryItem {
  key: string; type: LibraryKind; kind?: 'mcp' | 'builtin' | 'cli'; name: string; title?: string; description: string;
  when_to_use?: string; tags: string[]; status: 'installed' | 'available'; source?: string; server?: string;
  category: string | null; category_name: string; assigned_by: 'manual' | 'declared' | 'rule' | 'model' | 'fallback' | null;
  homepage?: string; stars?: number | null; last_updated?: string | null; official?: boolean;
  env_required?: string[]; windows?: boolean | null; pricing?: string | null; catalog?: boolean;
}

export interface OrganizeReport {
  scanned: number; assigned: number; by_declared: number; by_rule: number; by_model: number; by_fallback: number;
  unchanged: number; new_categories: Array<{ id: string; name: string }>; model_error: string | null;
  moved: Array<{ key: string; name: string; from: string | null; to: string; by: string }>; seconds: number; model?: 'on' | 'off';
}

export interface LibrarySnapshot {
  kind: LibraryKind; items: LibraryItem[]; categories: LibraryCategory[]; unorganized: number;
  installed: number; available: number; inbox: string; last_report: OrganizeReport | null;
}

export interface ImportResult { added: number; updated: number; errors: string[]; total: number; files?: number; inbox: string }

async function call<T>(base: string, path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...init?.headers } });
  } catch {
    throw new Error('连不上 Atlas 后端');
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    throw new Error(typeof body.detail === 'string' ? body.detail : `请求失败（HTTP ${response.status}）`);
  }
  return response.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: 'POST', body: JSON.stringify(body) });
const id = encodeURIComponent;

export const libraryApi = (base: string) => ({
  snapshot: (kind: LibraryKind) => call<LibrarySnapshot>(base, `/api/library?kind=${kind}`),
  organize: (full = false) => call<OrganizeReport>(base, '/api/library/organize', post({ full })),
  importText: (text: string) => call<ImportResult>(base, '/api/library/import', post({ text })),
  importInbox: () => call<ImportResult>(base, '/api/library/import', post({})),
  addCategory: (name: string, description = '') => call<LibraryCategory>(base, '/api/library/categories', post({ name, description })),
  renameCategory: (categoryId: string, name: string) =>
    call<LibraryCategory>(base, `/api/library/categories/${id(categoryId)}`, { method: 'PATCH', body: JSON.stringify({ name }) }),
  deleteCategory: (categoryId: string) => call<{ released: number }>(base, `/api/library/categories/${id(categoryId)}`, { method: 'DELETE' }),
  assign: (key: string, category: string | null) => call<{ key: string }>(base, '/api/library/assign', post({ key, category })),
  installSkill: (name: string) => call<{ installed: boolean }>(base, `/api/library/skills/${id(name)}/install`, post({})),
  installTool: (name: string, env: Record<string, string>) =>
    call<{ tool_count: number }>(base, `/api/library/tools/${id(name)}/install`, post({ env })),
  removeEntry: (key: string) => call<{ removed: boolean }>(base, '/api/library/catalog/remove', post({ key })),
});
