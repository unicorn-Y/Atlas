/**
 * MCP server settings, adapted to Atlas's existing MCP API.
 * Form/list interaction patterns ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f:
 * packages/ui/src/settings/McpSettingsSection.tsx, McpServerForm.tsx, and McpServerList.tsx (Apache-2.0).
 * Local/remote server configuration patterns also referenced anomalyco/opencode@7b3d4ce3a7dbd2a6d3637722a0d5f22a7d086937:
 * packages/app/src/settings/servers/ (MIT).
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Cable, LoaderCircle, Plus, RefreshCw, RotateCw, Trash2, X } from 'lucide-react';
import styles from '../../App.module.css';
import { Button } from '../../ui/Button';
import {
  addMcpServer,
  loadMcpServers,
  removeMcpServer,
  restartMcpServer,
  type McpServerRequest,
  type McpServerRow,
  type McpTransport,
} from '../../services/mcpSettingsApi';

type Draft = {
  name: string;
  transport: McpTransport;
  command: string;
  args: string;
  env: string;
  cwd: string;
  url: string;
};

const EMPTY_DRAFT: Draft = {
  name: '', transport: 'stdio', command: '', args: '', env: '', cwd: '', url: '',
};

const fieldClass = 'w-full rounded-[9px] bg-sunken px-3 py-2 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)] disabled:opacity-60';

function statusLabel(server: McpServerRow): string {
  if (!server.enabled) return '已停用';
  if (server.connected || server.state === 'connected') return '已连接';
  if (server.state === 'starting' || server.state === 'connecting') return '连接中';
  if (server.state === 'failed' || server.state === 'error') return '连接失败';
  if (server.state === 'stopped') return '已停止';
  return '未连接';
}

function statusClass(server: McpServerRow): string {
  if (server.connected || server.state === 'connected') return 'text-ok';
  if (server.state === 'failed' || server.state === 'error') return 'text-danger';
  if (!server.enabled || server.state === 'stopped') return 'text-fg-3';
  return 'text-fg-2';
}

function parseEnv(raw: string): Record<string, string> {
  if (!raw.trim()) return {};
  let value: unknown;
  try { value = JSON.parse(raw) as unknown; }
  catch { throw new Error('环境变量必须是有效的 JSON 对象。'); }
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('环境变量必须是键值对象，例如 {"API_KEY":"..."}。');
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.some(([key, item]) => !key.trim() || typeof item !== 'string')) {
    throw new Error('环境变量的键和值都必须是非空字符串。');
  }
  return Object.fromEntries(entries) as Record<string, string>;
}

function makeRequest(draft: Draft): McpServerRequest {
  const name = draft.name.trim();
  if (!name) throw new Error('请填写服务名称。');
  if (draft.transport === 'stdio') {
    if (!draft.command.trim()) throw new Error('stdio 服务需要启动命令。');
    return {
      name,
      transport: 'stdio',
      command: draft.command.trim(),
      args: draft.args.split(/\r?\n/).map((part) => part.trim()).filter(Boolean),
      env: parseEnv(draft.env),
      ...(draft.cwd.trim() ? { cwd: draft.cwd.trim() } : {}),
    };
  }
  const url = draft.url.trim();
  let parsed: URL;
  try { parsed = new URL(url); }
  catch { throw new Error('请填写有效的远程服务 URL。'); }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('远程服务 URL 必须使用 HTTP 或 HTTPS。');
  }
  return { name, transport: 'sse', url };
}

export default function McpServersPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [servers, setServers] = useState<McpServerRow[]>([]);
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [formOpen, setFormOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try { setServers(await loadMcpServers(apiBaseUrl)); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setLoading(false); }
  }, [apiBaseUrl]);

  useEffect(() => { void refresh(); }, [refresh]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError('');
    setNotice('');
    let request: McpServerRequest;
    try { request = makeRequest(draft); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); return; }
    setBusy('add');
    try {
      const created = await addMcpServer(apiBaseUrl, request);
      setNotice(`已添加 ${created.name}，发现 ${created.tool_count} 个工具。`);
      setDraft(EMPTY_DRAFT);
      setFormOpen(false);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally { setBusy(''); }
  };

  const restart = async (name: string) => {
    setBusy(`restart:${name}`);
    setError(''); setNotice('');
    try {
      const result = await restartMcpServer(apiBaseUrl, name);
      setNotice(`已重启 ${name}，当前有 ${result.tool_count} 个工具。`);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(''); }
  };

  const remove = async (name: string) => {
    if (confirmRemove !== name) { setConfirmRemove(name); return; }
    setBusy(`remove:${name}`);
    setError(''); setNotice(''); setConfirmRemove('');
    try {
      await removeMcpServer(apiBaseUrl, name);
      setNotice(`已移除 ${name}。`);
      await refresh();
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
    finally { setBusy(''); }
  };

  return <section className={styles.settingsCard} aria-label="MCP 服务管理">
    <div className={styles.settingsCardHeading}>
      <div>
        <h2>MCP 服务</h2>
        <p>管理可连接的本地 stdio 或远程 SSE 工具服务。</p>
      </div>
      <Button variant="secondary" size="sm" disabled={loading || Boolean(busy)} onClick={() => void refresh()}>
        {loading ? <LoaderCircle className="spin" /> : <RefreshCw />}刷新
      </Button>
    </div>

    {error && <p className={styles.settingsError} role="alert">{error}</p>}
    {notice && <p className={styles.settingsStatus} role="status">{notice}</p>}
    <p className="m-0 text-[12px] leading-[1.6] text-fg-3">
      当前 API 支持添加、重启和移除已连接的服务；配置读取、编辑和启停接口尚未提供。失败或停用的服务可在依赖检查中查看状态。
    </p>

    <div className="grid gap-2.5" aria-label="MCP 服务列表" aria-busy={loading}>
      {servers.map((server) => <article key={server.name} className="grid gap-2.5 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-2.5">
            <Cable size={16} className="mt-0.5 shrink-0 text-fg-3" />
            <div className="grid min-w-0 gap-1">
              <strong className="break-all text-[13px] font-medium text-fg">{server.name}</strong>
              <span className="text-[11.5px] text-fg-3">{server.transport === 'stdio' ? '本地 stdio' : server.transport === 'sse' ? '远程 SSE' : '传输方式未知'} · {server.tool_count} 个工具</span>
            </div>
          </div>
          <span className={`inline-flex items-center gap-1.5 text-[12px] ${statusClass(server)}`}>
            <i className={`size-1.5 rounded-full ${server.connected ? 'bg-ok' : server.state === 'failed' ? 'bg-danger' : 'bg-line-strong'}`} />
            {statusLabel(server)}
          </span>
        </div>
        {server.blocking_reason && <p className="m-0 rounded-lg bg-danger-soft px-2.5 py-2 text-[12px] leading-[1.5] text-danger">{server.blocking_reason}</p>}
        {server.tools.length > 0 && <details className="text-[12px] text-fg-3">
          <summary className="cursor-pointer select-none">查看工具（{server.tools.length}）</summary>
          <ul className="m-0 mt-1.5 grid gap-1 pl-5">
            {server.tools.map((tool) => <li key={tool} className="break-all">{tool}</li>)}
          </ul>
        </details>}
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" size="sm" disabled={!server.connected || Boolean(busy)} onClick={() => void restart(server.name)}>
            {busy === `restart:${server.name}` ? <LoaderCircle className="spin" /> : <RotateCw />}重启
          </Button>
          <Button variant={confirmRemove === server.name ? 'danger' : 'ghost'} size="sm" disabled={!server.connected || Boolean(busy)}
            onClick={() => void remove(server.name)} onBlur={() => setConfirmRemove((current) => current === server.name ? '' : current)}>
            {busy === `remove:${server.name}` ? <LoaderCircle className="spin" /> : confirmRemove === server.name ? <X /> : <Trash2 />}
            {confirmRemove === server.name ? '再点一次确认移除' : '移除'}
          </Button>
        </div>
      </article>)}
      {!loading && !servers.length && !error && <p className="m-0 rounded-xl bg-sunken px-3.5 py-4 text-[12.5px] text-fg-3">还没有可显示的 MCP 服务。可以添加一个本地或远程服务。</p>}
    </div>

    {!formOpen ? <Button variant="secondary" size="sm" disabled={Boolean(busy)} onClick={() => { setFormOpen(true); setError(''); setNotice(''); }}>
      <Plus />添加 MCP 服务
    </Button> : <form className="grid gap-3 rounded-xl bg-sunken p-3.5 shadow-[inset_0_0_0_1px_var(--line)]" onSubmit={(event) => void submit(event)}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="m-0 text-[13.5px] font-semibold text-fg">添加 MCP 服务</h3>
        <button type="button" aria-label="取消添加 MCP 服务" className="grid size-7 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg" onClick={() => { setFormOpen(false); setDraft(EMPTY_DRAFT); setError(''); }}><X size={15} /></button>
      </div>
      <label className="grid gap-1.5 text-[12px] text-fg-2">
        服务名称
        <input className={fieldClass} required value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="例如 filesystem" disabled={Boolean(busy)} />
      </label>
      <label className="grid gap-1.5 text-[12px] text-fg-2">
        连接方式
        <select className={fieldClass} value={draft.transport} onChange={(event) => setDraft({ ...draft, transport: event.target.value as McpTransport })} disabled={Boolean(busy)}>
          <option value="stdio">本地进程（stdio）</option>
          <option value="sse">远程服务（SSE）</option>
        </select>
      </label>
      {draft.transport === 'stdio' ? <>
        <label className="grid gap-1.5 text-[12px] text-fg-2">
          启动命令
          <input className={fieldClass} required value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} placeholder="npx" disabled={Boolean(busy)} />
        </label>
        <label className="grid gap-1.5 text-[12px] text-fg-2">
          参数（每行一个）
          <textarea className={`${fieldClass} min-h-20 resize-y font-mono`} value={draft.args} onChange={(event) => setDraft({ ...draft, args: event.target.value })} placeholder={'-y\n@modelcontextprotocol/server-filesystem\nD:/workspace'} disabled={Boolean(busy)} />
        </label>
        <label className="grid gap-1.5 text-[12px] text-fg-2">
          工作目录（可选）
          <input className={fieldClass} value={draft.cwd} onChange={(event) => setDraft({ ...draft, cwd: event.target.value })} placeholder="留空使用默认目录" disabled={Boolean(busy)} />
        </label>
        <label className="grid gap-1.5 text-[12px] text-fg-2">
          环境变量 JSON（可选）
          <textarea className={`${fieldClass} min-h-20 resize-y font-mono`} value={draft.env} onChange={(event) => setDraft({ ...draft, env: event.target.value })} placeholder={'{\n  "API_KEY": "..."\n}'} disabled={Boolean(busy)} />
        </label>
        <p className="m-0 text-[11.5px] text-fg-3">环境变量会写入 Atlas MCP 配置文件。请只填入需要传给该本地进程的值。</p>
      </> : <label className="grid gap-1.5 text-[12px] text-fg-2">
        远程 SSE URL
        <input className={fieldClass} required type="url" value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="https://example.com/sse" disabled={Boolean(busy)} />
      </label>}
      <div className="flex justify-end gap-2">
        <Button type="button" variant="ghost" size="sm" disabled={Boolean(busy)} onClick={() => { setFormOpen(false); setDraft(EMPTY_DRAFT); setError(''); }}>取消</Button>
        <Button type="submit" variant="primary" size="sm" disabled={Boolean(busy)}>
          {busy === 'add' ? <LoaderCircle className="spin" /> : <Plus />}添加并连接
        </Button>
      </div>
    </form>}
  </section>;
}
