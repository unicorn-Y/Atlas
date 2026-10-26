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

type McpResourceTemplate = {
  uri_template: string;
  name: string;
  title?: string | null;
  description?: string | null;
  mime_type?: string | null;
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

type ResourceTemplateServer = {
  name: string;
  enabled: boolean;
  connected: boolean;
  state: string;
  template_state: 'ready' | 'disconnected' | 'unsupported' | 'timeout' | 'limit_exceeded' | 'error';
  templates: McpResourceTemplate[];
  next_cursor?: string | null;
  error?: string | null;
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

type TemplateListResponse = { available: boolean; error?: string; servers: ResourceTemplateServer[] };
type TemplateReadResponse = { server_name: string; uri_template: string; uri: string; contents: ResourceContent[] };

function templateVariables(uriTemplate: string): string[] {
  const names = new Set<string>();
  for (const [, expression] of uriTemplate.matchAll(/\{([^{}]+)\}/g)) {
    const body = /^[+#./;?&]/.test(expression) ? expression.slice(1) : expression;
    for (const raw of body.split(',')) {
      const name = raw.replace(/(?::\d+|\*)+$/, '');
      if (/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(name)) names.add(name);
    }
  }
  return [...names];
}

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
  const [templateServers, setTemplateServers] = useState<ResourceTemplateServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState<{ server_name: string; uri: string } | null>(null);
  const [contents, setContents] = useState<ResourceContent[]>([]);
  const [templateError, setTemplateError] = useState('');
  const [selectedTemplate, setSelectedTemplate] = useState<{ server_name: string; template: McpResourceTemplate } | null>(null);
  const [templateValues, setTemplateValues] = useState<Record<string, string>>({});
  const [templateContents, setTemplateContents] = useState<ResourceContent[]>([]);
  const [resolvedTemplateUri, setResolvedTemplateUri] = useState('');
  const [templateBusy, setTemplateBusy] = useState(false);
  const [templateReadError, setTemplateReadError] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [response, templateResponse] = await Promise.all([
        api<ResourceListResponse>(apiBaseUrl, '/api/mcp/resources'),
        api<TemplateListResponse>(apiBaseUrl, '/api/mcp/resource-templates'),
      ]);
      if (!response.available) throw new Error(response.error || 'MCP runtime 不可用。');
      setServers(response.servers);
      if (!templateResponse.available) setTemplateError(templateResponse.error || 'MCP resource templates 不可用。');
      else { setTemplateServers(templateResponse.servers); setTemplateError(''); }
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

  const loadMoreTemplates = async (server: ResourceTemplateServer) => {
    if (!server.next_cursor) return;
    setTemplateError('');
    try {
      const query = new URLSearchParams({ server_name: server.name, cursor: server.next_cursor });
      const response = await api<TemplateListResponse>(apiBaseUrl, `/api/mcp/resource-templates?${query}`);
      const next = response.servers[0];
      if (next) setTemplateServers((current) => current.map((item) => item.name === server.name
        ? { ...item, templates: [...item.templates, ...next.templates], next_cursor: next.next_cursor } : item));
    } catch (cause) { setTemplateError(cause instanceof Error ? cause.message : String(cause)); }
  };

  const readTemplate = async () => {
    if (!selectedTemplate) return;
    setTemplateBusy(true); setTemplateReadError(''); setTemplateContents([]); setResolvedTemplateUri('');
    try {
      const result = await api<TemplateReadResponse>(apiBaseUrl, '/api/mcp/resource-templates/read', {
        method: 'POST', json: { server_name: selectedTemplate.server_name,
          uri_template: selectedTemplate.template.uri_template, variables: templateValues },
      });
      setResolvedTemplateUri(result.uri); setTemplateContents(result.contents);
    } catch (cause) { setTemplateReadError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setTemplateBusy(false); }
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

    <section className="grid gap-3" aria-label="MCP resource templates 浏览器">
      <div><h3 className="m-0 text-[14px] font-semibold text-fg">Resource templates</h3><p className="m-0 mt-1 text-[11.5px] text-fg-3">按 MCP 服务分组浏览 URI 模板，填写变量后读取资源。</p></div>
      {templateError && <p className="m-0 rounded-lg bg-danger-soft p-2.5 text-[12px] text-danger" role="alert">{templateError}</p>}
      {!templateServers.length && !templateError && !loading && <p className="m-0 rounded-xl bg-sunken px-3.5 py-3 text-[12px] text-fg-3">没有已连接服务声明 resource templates。</p>}
      {templateServers.map((server) => <article key={`templates:${server.name}`} className="grid gap-2 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <div className="flex flex-wrap items-center gap-2"><strong className="flex-1 break-all text-[12.5px] text-fg">{server.name}</strong><span className="text-[11px] text-fg-3">{server.template_state === 'ready' ? `模板 ${server.templates.length} 项` : server.template_state === 'unsupported' ? '未提供 templates/list' : server.template_state === 'timeout' ? '模板请求超时' : server.template_state === 'disconnected' ? '未连接' : server.template_state === 'limit_exceeded' ? '超过响应上限' : '读取失败'}</span></div>
        {server.error && <p className="m-0 text-[11.5px] text-danger" role="status">{server.error}</p>}
        {server.templates.map((template) => <button key={template.uri_template} type="button" onClick={() => {
          setSelectedTemplate({ server_name: server.name, template });
          setTemplateValues(Object.fromEntries(templateVariables(template.uri_template).map((name) => [name, ''])));
          setTemplateContents([]); setResolvedTemplateUri(''); setTemplateReadError('');
        }} className={`grid gap-1 rounded-lg px-2.5 py-2 text-left ${selectedTemplate?.server_name === server.name && selectedTemplate.template.uri_template === template.uri_template ? 'bg-hover' : 'hover:bg-hover'}`}>
          <span className="text-[12px] font-medium text-fg">{template.title || template.name || template.uri_template}</span><code className="break-all font-mono text-[10.5px] text-fg-3">{template.uri_template}</code>
          {(template.description || template.mime_type) && <span className="text-[11px] text-fg-3">{template.description || template.mime_type}</span>}
        </button>)}
        {server.next_cursor && <Button variant="ghost" size="sm" disabled={Boolean(busy) || templateBusy} onClick={() => void loadMoreTemplates(server)}>继续加载模板</Button>}
        {server.template_state === 'ready' && !server.templates.length && <p className="m-0 text-[11px] text-fg-3">此服务当前未声明 resource templates。</p>}
      </article>)}
    </section>

    {selectedTemplate && <section className="grid gap-2 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="MCP resource template 参数和内容" aria-busy={templateBusy}>
      <div><h3 className="m-0 text-[13px] font-semibold text-fg">{selectedTemplate.server_name} · {selectedTemplate.template.title || selectedTemplate.template.name || 'Resource template'}</h3><code className="break-all text-[10.5px] text-fg-3">{selectedTemplate.template.uri_template}</code></div>
      {templateVariables(selectedTemplate.template.uri_template).map((name) => <label key={name} className="grid gap-1 text-[11.5px] text-fg-2">{name}<input aria-label={`模板参数 ${name}`} value={templateValues[name] ?? ''} onChange={(event) => setTemplateValues((current) => ({ ...current, [name]: event.target.value }))} className="h-8 rounded-lg bg-canvas px-2.5 text-[12px] text-fg" /></label>)}
      {!templateVariables(selectedTemplate.template.uri_template).length && <p className="m-0 text-[11px] text-fg-3">此 URI 模板不含变量。</p>}
      <Button variant="secondary" size="sm" disabled={templateBusy} onClick={() => void readTemplate()}>{templateBusy ? <LoaderCircle className="spin" /> : <FileText />}读取模板资源</Button>
      {templateReadError && <p className="m-0 rounded-lg bg-danger-soft p-2.5 text-[12px] text-danger" role="alert">{templateReadError}</p>}
      {resolvedTemplateUri && <code className="break-all text-[10.5px] text-fg-3">解析 URI：{resolvedTemplateUri}</code>}
      {templateContents.map((item, index) => item.type === 'text' ? <pre key={`${item.uri}:${index}`} className="m-0 max-h-[420px] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-canvas p-3 text-[12px] leading-relaxed text-fg">{item.text}</pre> : <div key={`${item.uri}:${index}`} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-canvas p-3 text-[12px] text-fg-2"><span>{item.mime_type || '二进制资源'} · 模板资源内容</span><Button variant="secondary" size="sm" disabled={!item.base64} onClick={() => saveBlob(item)}><Download />下载</Button></div>)}
      {!templateBusy && resolvedTemplateUri && !templateContents.length && !templateReadError && <p className="m-0 text-[12px] text-fg-3">服务返回了空内容。</p>}
    </section>}

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
