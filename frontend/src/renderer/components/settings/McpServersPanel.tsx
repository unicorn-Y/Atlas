import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Button } from '../../ui/Button';
import { api } from '../../services/api';
import styles from '../../App.module.css';

type Config = {
  name: string; transport: 'stdio' | 'sse' | 'streamable_http'; command: string; args: string[];
  env: Record<string, string>; cwd: string | null; url: string; headers: Record<string, string>;
  enabled: boolean; startup_timeout: number; oauth: boolean; oauth_scope: string;
};
type Row = Config & { connected: boolean; connecting: boolean; state: string; tool_count: number;
  tools: string[]; blocking_reason?: string; auth?: { state: string; message: string } };
type Draft = Config & { argsText: string; envText: string; headersText: string };
const empty = (): Draft => ({ name: '', transport: 'stdio', command: '', args: [], argsText: '', env: {}, envText: '{}', cwd: null,
  url: '', headers: {}, headersText: '{}', enabled: true, startup_timeout: 30, oauth: false, oauth_scope: '' });
const field = 'w-full rounded-lg bg-sunken p-2 text-[12px] text-fg shadow-[inset_0_0_0_1px_var(--line)]';
function jsonMap(value: string): Record<string, string> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed) || Object.values(parsed).some((item) => typeof item !== 'string')) throw new Error('环境变量和 headers 必须是字符串键值 JSON 对象');
  return parsed as Record<string, string>;
}
const configOnly = (row: Row): Config => ({ name: row.name, transport: row.transport, command: row.command || '', args: row.args || [],
  env: row.env || {}, cwd: row.cwd || null, url: row.url || '', headers: row.headers || {}, enabled: row.enabled,
  startup_timeout: row.startup_timeout || 30, oauth: row.oauth || false, oauth_scope: row.oauth_scope || '' });

export default function McpServersPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [servers, setServers] = useState<Row[]>([]);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [editing, setEditing] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmRemove, setConfirmRemove] = useState('');
  const refresh = useCallback(async () => {
    try { const result = await api<{ servers: Row[] }>(apiBaseUrl, '/api/mcp/configs'); setServers(result.servers); }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); }
  }, [apiBaseUrl]);
  useEffect(() => { void refresh(); const timer = window.setInterval(() => void refresh(), 3000); return () => window.clearInterval(timer); }, [refresh]);
  const act = async (path: string, method: 'POST' | 'PUT' | 'DELETE', json?: Config) => {
    setBusy(true); setError(''); setNotice('');
    try { await api(apiBaseUrl, path, { method, ...(json ? { json } : {}) }); await refresh(); return true; }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); return false; }
    finally { setBusy(false); }
  };
  const save = async (event: FormEvent) => {
    event.preventDefault(); if (!draft) return;
    let value: Config;
    try { value = { name: draft.name.trim(), transport: draft.transport, command: draft.command,
      args: draft.argsText.split(/\r?\n/).filter(Boolean), env: jsonMap(draft.envText), cwd: draft.cwd || null,
      url: draft.url.trim(), headers: jsonMap(draft.headersText), enabled: draft.enabled,
      startup_timeout: draft.startup_timeout, oauth: draft.transport !== 'stdio' && draft.oauth, oauth_scope: draft.oauth_scope };
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)); return; }
    if (await act(editing ? '/api/mcp/configs/' + encodeURIComponent(editing) : '/api/mcp/configs', editing ? 'PUT' : 'POST', value)) {
      setDraft(null); setNotice('配置已保存。启用的服务正在连接，状态会自动刷新；失败配置可继续编辑。');
    }
  };
  return <section className={styles.settingsCard} aria-label="MCP 服务管理">
    <div className={styles.settingsCardHeading}><div><h2>MCP 服务</h2><p>管理 stdio、SSE、Streamable HTTP 和 OAuth 浏览器授权。</p></div>
      <Button size="sm" disabled={busy} onClick={() => void refresh()}>刷新</Button></div>
    <p className="text-[12px] text-fg-3">配置作用于此用户。项目/Agent scope 与逐工具规则尚未支持。环境变量和 headers 写入本机配置；OAuth tokens 存入系统凭据保险箱。</p>
    {error && <p role="alert" className={styles.settingsError}>{error}</p>}{notice && <p role="status" className={styles.settingsStatus}>{notice}</p>}
    {servers.map((row) => <article key={row.name} className="grid gap-2 rounded-xl bg-sunken p-3 text-[12px]">
      <div className="flex justify-between"><strong>{row.name}</strong><span>{row.enabled ? row.connected ? '已连接' : row.connecting ? '连接中' : row.state : '已停用'} · {row.transport} · {row.tool_count} 个工具</span></div>
      {row.blocking_reason && <p role="status" className="text-danger">{row.blocking_reason}</p>}{row.auth && <p role="status">{row.auth.message}</p>}
      {row.tools.length > 0 && <details><summary>工具列表</summary><ul>{row.tools.map((tool) => <li key={tool}>{tool}</li>)}</ul></details>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={busy} onClick={() => { const config = configOnly(row); setEditing(row.name); setDraft({ ...config, argsText: config.args.join('\n'), envText: JSON.stringify(config.env, null, 2), headersText: JSON.stringify(config.headers, null, 2) }); }}>编辑</Button>
        <Button size="sm" disabled={busy} onClick={() => void act('/api/mcp/configs/' + encodeURIComponent(row.name), 'PUT', { ...configOnly(row), enabled: !row.enabled })}>{row.enabled ? '停用' : '启用'}</Button>
        <Button size="sm" disabled={busy || !row.enabled} onClick={() => void act('/api/mcp/configs/' + encodeURIComponent(row.name) + '/reconnect', 'POST')}>重新连接</Button>
        {row.oauth && <Button size="sm" disabled={busy} onClick={() => void act('/api/mcp/configs/' + encodeURIComponent(row.name) + '/reauthorize', 'POST')}>重新授权</Button>}
        <Button size="sm" variant="danger" disabled={busy} onClick={() => { if (confirmRemove !== row.name) { setConfirmRemove(row.name); return; } void act('/api/mcp/configs/' + encodeURIComponent(row.name), 'DELETE'); setConfirmRemove(''); }}>{confirmRemove === row.name ? '再次点击确认删除' : '删除'}</Button>
      </div></article>)}
    {!draft ? <Button size="sm" onClick={() => { setEditing(''); setDraft(empty()); }}>添加 MCP 服务</Button> : <form className="grid gap-3 text-[12px]" onSubmit={(event) => void save(event)}>
      <label>名称<input required disabled={Boolean(editing)} className={field} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} /></label>
      <label>连接方式<select className={field} value={draft.transport} onChange={(event) => setDraft({ ...draft, transport: event.target.value as Config['transport'], oauth: false })}><option value="stdio">本地 stdio</option><option value="sse">远程 SSE</option><option value="streamable_http">Streamable HTTP</option></select></label>
      {draft.transport === 'stdio' ? <><label>启动命令<input required className={field} value={draft.command} onChange={(event) => setDraft({ ...draft, command: event.target.value })} /></label><label>参数（每行一个）<textarea className={field} value={draft.argsText} onChange={(event) => setDraft({ ...draft, argsText: event.target.value })} /></label><label>工作目录<input className={field} value={draft.cwd || ''} onChange={(event) => setDraft({ ...draft, cwd: event.target.value })} /></label><label>环境变量 JSON<textarea className={field} value={draft.envText} onChange={(event) => setDraft({ ...draft, envText: event.target.value })} /></label></> : <>
        <label>URL<input required type="url" className={field} value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} /></label>
        <label>Headers JSON<textarea className={field} value={draft.headersText} onChange={(event) => setDraft({ ...draft, headersText: event.target.value })} /></label>
        <label><input type="checkbox" checked={draft.oauth} onChange={(event) => setDraft({ ...draft, oauth: event.target.checked })} /> OAuth（PKCE 浏览器授权）</label>
        {draft.oauth && <label>OAuth scopes（空格分隔）<input className={field} value={draft.oauth_scope} onChange={(event) => setDraft({ ...draft, oauth_scope: event.target.value })} /></label>}
      </>}
      <p className="text-fg-3">******** 保留已保存值；替换为新值可更新，删除键可移除。OAuth 与静态 Authorization header 不能同时使用。</p>
      <label>连接超时（秒；OAuth 至少允许 200 秒）<input className={field} type="number" min={1} max={300} required value={draft.startup_timeout} onChange={(event) => setDraft({ ...draft, startup_timeout: Number(event.target.value) })} /></label>
      <label><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /> 保存后启用</label>
      <div className="flex gap-2"><Button type="submit" disabled={busy}>保存</Button><Button type="button" disabled={busy} onClick={() => setDraft(null)}>取消</Button></div>
    </form>}
  </section>;
}
