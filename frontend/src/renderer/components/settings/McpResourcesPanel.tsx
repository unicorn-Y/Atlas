/**
 * MCP resource browser backed by Atlas' connected MCP sessions. The backend
 * uses MCP Python SDK ClientSession.list_resources/read_resource; no tool
 * invocation schemas or synthetic resource rows are exposed here.
 */
import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Download, FileText, LoaderCircle, RefreshCw, RotateCw } from 'lucide-react';
import styles from '../../App.module.css';
import { Button } from '../../ui/Button';
import { api } from '../../services/api';

type McpResource = {
  uri: string;
  name: string;
  title?: string | null;
  description?: string | null;
  mime_type?: string | null;
  size?: number | null;
};

type McpResourceServer = {
  name: string;
  enabled: boolean;
  connected: boolean;
  state: string;
  resource_state: 'ready' | 'disconnected' | 'unsupported' | 'timeout' | 'limit_exceeded' | 'error';
  resources: McpResource[];
  error?: string | null;
  error_code?: number | null;
};

type ResourceListResponse = {
  available: boolean;
  error?: string;
  servers: McpResourceServer[];
};

type ResourceContent = {
  uri: string;
  mime_type?: string | null;
  type: 'text' | 'blob';
  text?: string;
  base64?: string;
};

type ResourceReadResponse = {
  server_name: string;
  uri: string;
  contents: ResourceContent[];
};

function lifecycleLabel(server: McpResourceServer): string {
  if (!server.enabled) return '已停用';
  if (server.connected) return '已连接';
  if (server.state === 'failed' || server.state === 'error') return '连接失败';
  if (server.state === 'starting' || server.state === 'connecting') return '连接中';
  if (server.state === 'stopped') return '已停止';
  return '未连接';
}

function resourceStateLabel(server: McpResourceServer): string {
  if (server.resource_state === 'ready') return `资源 ${server.resources.length} 项`;
  if (server.resource_state === 'unsupported') return '服务未提供资源接口';
  if (server.resource_state === 'timeout') return '资源请求超时';
  if (server.resource_state === 'limit_exceeded') return '资源响应超过安全上限';
  if (server.resource_state === 'disconnected') return '当前未连接';
  return '资源读取失败';
}

function saveBlob(item: ResourceContent) {
  if (!item.base64) return;
  const binary = window.atob(item.base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  const blob = new Blob([bytes], { type: item.mime_type || 'application/octet-stream' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = item.uri.split(/[?#]/, 1)[0].split('/').filter(Boolean).pop() || 'mcp-resource';
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function McpResourcesPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [servers, setServers] = useState<McpResourceServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<{ server_name: string; uri: string } | null>(null);
  const [contents, setContents] = useState<ResourceContent[]>([]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const response = await api<ResourceListResponse>(apiBaseUrl, '/api/mcp/resources');
      if (!response.available) throw new Error(response.error || 'MCP runtime 不可用。');
      setServers(response.servers);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const read = async (server: McpResourceServer, resource: McpResource) => {
    setBusy(`read:${server.name}:${resource.uri}`);
    setError('');
    setNotice('');
    setContents([]);
    setSelected({ server_name: server.name, uri: resource.uri });
    try {
      const result = await api<ResourceReadResponse>(apiBaseUrl, '/api/mcp/resources/read', {
        method: 'POST',
        json: { server_name: server.name, uri: resource.uri },
      });
      setContents(result.contents);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy('');
    }
  };

  const restart = async (server: McpResourceServer) => {
    setBusy(`restart:${server.name}`);
    setError('');
    setNotice('');
    try {
      await api(apiBaseUrl, `/api/mcp/servers/${encodeURIComponent(server.name)}/restart`, { method: 'POST' });
      setNotice(`已重启 ${server.name}，正在刷新资源和连接状态。`);
      setSelected(null);
      setContents([]);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy('');
    }
  };

  return <section className={styles.settingsCard} aria-label="MCP 资源浏览器">
    <div className={styles.settingsCardHeading}>
      <div>
        <h2>MCP 资源</h2>
        <p>浏览当前已连接服务实际声明的资源，并读取选中的 URI。</p>
      </div>
      <Button variant="secondary" size="sm" disabled={loading || Boolean(busy)} onClick={() => void refresh()}>
        {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新
      </Button>
    </div>

    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {notice && <p className={styles.settingsStatus} role="status">{notice}</p>}
    <p className="m-0 text-[12px] leading-[1.6] text-fg-3">
      这里只显示 MCP 服务返回的 resources/list 内容。工具输入参数不会展示；服务未实现资源接口、断开或读取失败时会标明状态。
    </p>

    <div className="grid gap-3" aria-label="MCP 资源服务列表" aria-busy={loading}>
      {servers.map((server) => <article key={server.name} className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="grid min-w-0 gap-1">
            <strong className="break-all text-[13px] font-medium text-fg">{server.name}</strong>
            <span className="text-[11.5px] text-fg-3">{lifecycleLabel(server)} · {resourceStateLabel(server)}</span>
          </div>
          <Button variant="ghost" size="sm" disabled={!server.connected || Boolean(busy)} onClick={() => void restart(server)}>
            {busy === `restart:${server.name}` ? <LoaderCircle className="spin" /> : <RotateCw />}重启服务
          </Button>
        </div>
        {server.error && <p className="m-0 rounded-lg bg-danger-soft px-2.5 py-2 text-[12px] leading-[1.5] text-danger" role="status">
          <AlertCircle className="mr-1 inline size-3.5 align-[-2px]" />{server.error}
          {server.error_code !== null && server.error_code !== undefined ? `（错误码 ${server.error_code}）` : ''}
        </p>}
        {server.resource_state === 'ready' && server.resources.length > 0 && <ul className="m-0 grid gap-1.5 p-0">
          {server.resources.map((resource) => {
            const isSelected = selected?.server_name === server.name && selected.uri === resource.uri;
            return <li key={resource.uri} className="list-none">
              <button type="button" className={`grid w-full gap-1 rounded-lg px-2.5 py-2 text-left ${isSelected ? 'bg-hover' : 'hover:bg-hover'}`} disabled={Boolean(busy)} onClick={() => void read(server, resource)}>
                <span className="flex min-w-0 items-center gap-2 text-[12px] font-medium text-fg"><FileText className="size-3.5 shrink-0 text-fg-3" />{resource.title || resource.name || resource.uri}</span>
                <span className="break-all pl-[22px] font-mono text-[10.5px] text-fg-3">{resource.uri}</span>
                {(resource.description || resource.mime_type) && <span className="pl-[22px] text-[11px] text-fg-3">{resource.description || resource.mime_type}</span>}
              </button>
            </li>;
          })}
        </ul>}
        {server.resource_state === 'ready' && server.resources.length === 0 && <p className="m-0 text-[12px] text-fg-3">此服务当前未声明资源。</p>}
      </article>)}
      {!loading && !servers.length && !error && <p className="m-0 rounded-xl bg-sunken px-3.5 py-4 text-[12.5px] text-fg-3">没有已配置的 MCP 服务。</p>}
      {loading && !servers.length && <p className="m-0 text-[12px] text-fg-3">正在读取 MCP 资源与连接状态…</p>}
    </div>

    {selected && <section className="grid gap-2 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="MCP 资源内容" aria-busy={busy.startsWith('read:')}>
      <div className="grid gap-1">
        <h3 className="m-0 text-[13px] font-semibold text-fg">{selected.server_name} · 资源内容</h3>
        <code className="break-all text-[10.5px] text-fg-3">{selected.uri}</code>
      </div>
      {busy.startsWith('read:') && <p className="m-0 text-[12px] text-fg-3"><LoaderCircle className="mr-1 inline size-3.5 animate-spin" />正在读取…</p>}
      {!busy.startsWith('read:') && !contents.length && !error && <p className="m-0 text-[12px] text-fg-3">服务返回了空内容。</p>}
      {contents.map((item, index) => item.type === 'text' ? <pre key={`${item.uri}:${index}`} className="m-0 max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-canvas p-3 text-[12px] leading-relaxed text-fg">{item.text}</pre> : <div key={`${item.uri}:${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-canvas p-3 text-[12px] text-fg-2">
        <span>{item.mime_type || '二进制资源'} · Base64 内容可下载</span>
        <Button variant="secondary" size="sm" disabled={!item.base64} onClick={() => saveBlob(item)}><Download />下载</Button>
      </div>)}
    </section>}
  </section>;
}
