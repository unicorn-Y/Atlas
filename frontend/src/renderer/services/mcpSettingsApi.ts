/**
 * Atlas MCP settings API adapter. UI interaction patterns are informed by
 * zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f (Apache-2.0) and
 * anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937 (MIT).
 */
export type McpTransport = 'stdio' | 'sse' | 'streamable_http';

export interface McpServerToolListItem {
  name: string;
  tool_count: number;
  tools: string[];
}

export interface McpRuntimeServer {
  name: string;
  enabled: boolean;
  transport: McpTransport | 'unknown';
  connected: boolean;
  state: string;
  tool_count: number;
  blocking_reason?: string | null;
  diagnostic?: string | null;
  allowed_tools?: string[] | null;
  header_names?: string[];
  url?: string;
}

export interface McpServerRow extends McpRuntimeServer {
  tools: string[];
}

export interface McpServerRequest {
  name: string;
  transport: McpTransport;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  cwd?: string;
  url?: string;
  headers?: Record<string, string>;
}

export interface McpServerSettingsPatch {
  enabled?: boolean;
  allowed_tools?: string[] | null;
  headers?: Record<string, string>;
}

interface McpServerListResponse {
  servers?: McpServerToolListItem[];
}

async function request<T>(baseUrl: string, path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    headers: { ...(init?.body ? { 'Content-Type': 'application/json' } : {}), ...init?.headers },
  });
  const text = await response.text();
  let body: unknown;
  try { body = text ? JSON.parse(text) as unknown : null; } catch { body = text; }
  if (!response.ok) {
    const detail = body && typeof body === 'object' && 'detail' in body ? String(body.detail) : '';
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return body as T;
}

export async function loadMcpServers(baseUrl: string): Promise<McpServerRow[]> {
  const [liveResult, runtimeResult] = await Promise.allSettled([
    request<McpServerListResponse>(baseUrl, '/api/mcp/servers'),
    request<{ servers?: McpRuntimeServer[] }>(baseUrl, '/api/mcp/settings/servers'),
  ]);
  if (liveResult.status === 'rejected' && runtimeResult.status === 'rejected') {
    throw liveResult.reason instanceof Error ? liveResult.reason : new Error('无法读取 MCP 服务');
  }

  const toolsByName = new Map<string, string[]>();
  if (liveResult.status === 'fulfilled') {
    for (const server of liveResult.value.servers ?? []) toolsByName.set(server.name, server.tools ?? []);
  }
  const runtimeServers = runtimeResult.status === 'fulfilled'
    ? runtimeResult.value.servers ?? []
    : [];
  const rows: McpServerRow[] = runtimeServers.map((server) => ({
    ...server,
    tools: toolsByName.get(server.name) ?? [],
  }));

  if (!runtimeServers.length && liveResult.status === 'fulfilled') {
    for (const server of liveResult.value.servers ?? []) {
      rows.push({
        name: server.name,
        enabled: true,
        transport: 'unknown',
        connected: true,
        state: 'connected',
        tool_count: server.tool_count,
        tools: server.tools ?? [],
      });
    }
  }
  return rows;
}

export function addMcpServer(baseUrl: string, config: McpServerRequest): Promise<McpServerToolListItem> {
  return request(baseUrl, '/api/mcp/servers', { method: 'POST', body: JSON.stringify(config) });
}

export function restartMcpServer(baseUrl: string, name: string): Promise<McpServerToolListItem> {
  return request(baseUrl, `/api/mcp/servers/${encodeURIComponent(name)}/restart`, { method: 'POST' });
}

export function removeMcpServer(baseUrl: string, name: string): Promise<{ status: string }> {
  return request(baseUrl, `/api/mcp/servers/${encodeURIComponent(name)}`, { method: 'DELETE' });
}

export function patchMcpServerSettings(
  baseUrl: string,
  name: string,
  patch: McpServerSettingsPatch,
): Promise<McpRuntimeServer> {
  return request(baseUrl, `/api/mcp/settings/servers/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });
}
