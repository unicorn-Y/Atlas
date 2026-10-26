import { useCallback, useEffect, useState } from 'react';
import { ArrowLeft, Copy, LoaderCircle, Plus, RefreshCw, RotateCw, Server, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import { field } from './agents/shared';

interface Peer { id: string; name: string; url: string; created_at?: string; last_seen?: string; health?: string; error?: string; version?: string; capabilities?: string[] }
interface Session { id: string; title: string; workspace: string; run_id: string; status: string; waiting_for?: string | null }
interface Instance extends Peer { sessions?: Session[] }
interface QueueItem { id: string; peer_id: string; title: string; status: string; created_at: string; last_error?: string }
interface ClusterSettings { node_id: string; node_name: string; service_token: string }
interface InstanceResponse { instances: Instance[]; queue: QueueItem[] }
interface AuditRow { id: string; time: string; action: string; peer_id: string; subject_id: string; result: string; detail: string }

export default function ClusterControlPage({ apiBaseUrl, onBack, onToast }: { apiBaseUrl: string; onBack: () => void; onToast: (message: string) => void }) {
  const [settings, setSettings] = useState<ClusterSettings | null>(null);
  const [name, setName] = useState('');
  const [showToken, setShowToken] = useState(false);
  const [peers, setPeers] = useState<Peer[]>([]);
  const [instances, setInstances] = useState<Instance[]>([]);
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [auditRows, setAuditRows] = useState<AuditRow[]>([]);
  const [form, setForm] = useState({ name: '', url: '', token: '' });
  const [task, setTask] = useState({ peer_id: '', title: '', content: '', workspace: '' });
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  const loadInstances = useCallback(async () => {
    setBusy('refresh'); setError('');
    try {
      const config = await api<ClusterSettings>(apiBaseUrl, '/api/cluster/settings');
      setSettings(config); setName(config.node_name);
      const nodeData = await api<{ self: { id: string; name: string }; peers: Peer[]; queue: QueueItem[] }>(apiBaseUrl, '/api/cluster/nodes', { headers: { 'X-Atlas-Cluster-Token': config.service_token } });
      setPeers(nodeData.peers); setQueue(nodeData.queue);
      if (!task.peer_id && nodeData.peers[0]) setTask((value) => ({ ...value, peer_id: nodeData.peers[0].id }));
      const status = await api<InstanceResponse>(apiBaseUrl, '/api/cluster/instances', { headers: { 'X-Atlas-Cluster-Token': config.service_token } });
      setInstances(status.instances); setQueue(status.queue);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  }, [apiBaseUrl, task.peer_id]);

  useEffect(() => {
    void loadInstances();
    const timer = window.setInterval(() => { void loadInstances(); }, 15_000);
    return () => window.clearInterval(timer);
  }, [loadInstances]);

  const saveName = async () => {
    setBusy('name'); setError('');
    try { await api(apiBaseUrl, '/api/cluster/settings', { method: 'PUT', json: { node_name: name } }); onToast('此 Atlas 实例名称已保存'); await loadInstances(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const addPeer = async () => {
    setBusy('peer'); setError('');
    try {
      const peer = await api<Peer>(apiBaseUrl, '/api/cluster/nodes', { method: 'POST', json: form });
      setForm({ name: '', url: '', token: '' }); setTask((value) => ({ ...value, peer_id: peer.id }));
      onToast(`已连接节点 ${peer.name}`); await loadInstances();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const removePeer = async (peer: Peer) => {
    setBusy(peer.id); setError('');
    try { await api(apiBaseUrl, `/api/cluster/nodes/${encodeURIComponent(peer.id)}`, { method: 'DELETE' }); onToast(`已撤销节点 ${peer.name}`); await loadInstances(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const rotateToken = async () => {
    setBusy('token'); setError('');
    try { const result = await api<{ node_id: string; service_token: string }>(apiBaseUrl, '/api/cluster/token/rotate', { method: 'POST' }); setSettings((old) => old ? { ...old, ...result } : old); setShowToken(true); onToast('节点配对令牌已轮换；需要在已配对节点上更新此令牌。'); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const routeTask = async () => {
    if (!task.peer_id || !task.content.trim()) { setError('选择目标节点并填写任务内容。'); return; }
    setBusy('task'); setError('');
    try {
      const result = await api<{ status: string; message?: string; run_id?: string; id?: string }>(apiBaseUrl,
        `/api/cluster/nodes/${encodeURIComponent(task.peer_id)}/tasks`, { method: 'POST', json: task });
      onToast(result.status === 'queued' ? result.message ?? '任务已进入离线队列' : `任务已路由；远端运行 ${result.run_id ?? ''}`);
      setTask((value) => ({ ...value, title: '', content: '' })); await loadInstances();
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const operate = async (peerId: string, session: Session, action: 'pause' | 'resume' | 'cancel') => {
    setBusy(session.run_id); setError('');
    try { await api(apiBaseUrl, `/api/cluster/nodes/${encodeURIComponent(peerId)}/runs/${encodeURIComponent(session.run_id)}/${action}`, { method: 'POST' }); onToast(`远端运行已${action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '取消'}`); await loadInstances(); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const loadAudit = async () => {
    if (!settings) return;
    try { const result = await api<{ events: AuditRow[] }>(apiBaseUrl, '/api/cluster/audit', { headers: { 'X-Atlas-Cluster-Token': settings.service_token } }); setAuditRows(result.events); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  };

  return <main className="screen page"><div className="page-inner max-w-6xl">
    <header className="flex flex-wrap items-center gap-3">
      <Button variant="ghost" onClick={onBack} aria-label="返回设备页"><ArrowLeft size={15} /> 设备与配对</Button>
      <div className="min-w-0 flex-1"><h1>Atlas 多机集群</h1><p>登记可信 Atlas 实例、查看心跳和会话，并路由任务或控制远端运行。</p></div>
      <Button variant="ghost" onClick={() => void loadInstances()} disabled={busy === 'refresh'} aria-label="刷新集群状态">{busy === 'refresh' ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} 刷新</Button>
    </header>
    {error && <p role="alert" className="mt-4 rounded-lg bg-danger-soft px-3 py-2 text-[12.5px] text-danger">{error}</p>}
    {settings && <section className="mt-5 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="本机 Atlas 节点身份">
      <h2 className="m-0 text-[14px] font-semibold">本机节点身份与配对令牌</h2>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="grid min-w-[220px] flex-1 gap-1 text-[12px] text-fg-2">节点名称<input aria-label="本机节点名称" className={field} value={name} onChange={(event) => setName(event.target.value)} /></label>
        <Button variant="secondary" onClick={() => void saveName()} disabled={busy === 'name'}>保存名称</Button>
      </div>
      <p className="mb-1 mt-3 text-[11.5px] text-fg-3">节点 ID：<code className="select-all font-mono">{settings.node_id}</code></p>
      <div className="flex flex-wrap items-center gap-2">
        <label className="min-w-[260px] flex-1 text-[12px] text-fg-2">本机服务令牌
          <input aria-label="本机集群服务令牌" type={showToken ? 'text' : 'password'} readOnly value={settings.service_token} className={cn(field, 'mt-1 font-mono')} />
        </label>
        <Button variant="secondary" onClick={() => setShowToken((value) => !value)}>{showToken ? '隐藏' : '显示'}</Button>
        <Button variant="secondary" onClick={() => void navigator.clipboard.writeText(settings.service_token).then(() => onToast('已复制配对令牌'))}><Copy size={14} />复制</Button>
        <Button variant="ghost" onClick={() => void rotateToken()} disabled={busy === 'token'}><RotateCw size={14} />轮换令牌</Button>
      </div>
      <p className="mb-0 mt-2 text-[11px] text-fg-3">令牌只保存在本机 Atlas 设置文件；将目标节点 URL 与令牌填入另一台 Atlas 的节点登记表即可配对。轮换后需同步更新对端保存的令牌。</p>
    </section>}
    <section className="mt-5 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="登记远程 Atlas 节点">
      <h2 className="m-0 text-[14px] font-semibold">登记可信节点</h2><p className="mb-3 mt-1 text-[11.5px] text-fg-3">保存前会使用令牌验证节点身份与协议版本；撤销节点会移除本机凭据，并停止向该节点路由。</p>
      <div className="grid gap-2 md:grid-cols-3">
        <input aria-label="远程节点名称" className={field} placeholder="节点名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
        <input aria-label="远程节点 URL" className={field} placeholder="http://127.0.0.1:8766" value={form.url} onChange={(event) => setForm({ ...form, url: event.target.value })} />
        <input aria-label="远程节点令牌" className={cn(field, 'font-mono')} type="password" autoComplete="off" placeholder="粘贴对端服务令牌" value={form.token} onChange={(event) => setForm({ ...form, token: event.target.value })} />
      </div>
      <Button className="mt-2" onClick={() => void addPeer()} disabled={busy === 'peer'}><Plus size={14} />验证并登记</Button>
    </section>
    <section className="mt-5" aria-label="Atlas 实例、健康与会话">
      <h2 className="mb-2 flex items-center gap-2 px-1 text-[14px] font-semibold"><Server size={15} />实例、健康与会话</h2>
      <div className="grid gap-3">
        {instances.map((instance) => <article key={instance.id} className="rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]">
          <div className="flex flex-wrap items-center gap-2"><b className="min-w-0 flex-1 truncate">{instance.name}</b><span className={cn('rounded px-2 py-0.5 text-[11px]', instance.health === 'online' ? 'bg-ok-soft text-ok' : 'bg-danger-soft text-danger')}>{instance.health === 'online' ? '在线' : '离线'}</span><code className="text-[10.5px] text-fg-3">{instance.id}</code>{instance.url !== 'local' && <Button variant="ghost" onClick={() => void removePeer(instance)} disabled={busy === instance.id} aria-label={`撤销节点 ${instance.name}`}><Trash2 size={14} />撤销</Button>}</div>
          <p className="mb-1 mt-1 text-[11px] text-fg-3">{instance.url} · Atlas {instance.version ?? '版本未知'} · 最近心跳 {instance.last_seen ? new Date(instance.last_seen).toLocaleString() : '尚无'}</p>
          {!!instance.capabilities?.length && <p className="mb-2 mt-0 text-[10.5px] text-fg-3">能力：{instance.capabilities.join(' · ')}</p>}
          {instance.error && <p className="text-[11.5px] text-danger">离线原因：{instance.error}</p>}
          <div className="grid gap-1.5">
            {(instance.sessions ?? []).map((session) => <div key={session.id} className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken px-3 py-2 text-[11.5px]">
              <span className="min-w-0 flex-1 truncate"><b>{session.title}</b><small className="ml-2 text-fg-3">{session.workspace} · {session.status}{session.waiting_for ? ` · 等待 ${session.waiting_for}` : ''}</small></span>
              {session.run_id && ['running', 'paused', 'waiting'].includes(session.status) && <><Button variant="ghost" disabled={busy === session.run_id} onClick={() => void operate(instance.id, session, session.status === 'paused' ? 'resume' : 'pause')}>{session.status === 'paused' ? '继续' : '暂停'}</Button><Button variant="ghost" disabled={busy === session.run_id} onClick={() => void operate(instance.id, session, 'cancel')}>取消</Button></>}
            </div>)}
            {instance.health === 'online' && !instance.sessions?.length && <p className="m-0 px-1 py-2 text-[11.5px] text-fg-3">此实例当前没有会话。</p>}
            {instance.health === 'offline' && <p className="m-0 px-1 py-2 text-[11.5px] text-fg-3">实例离线；新任务会进入本机队列，恢复后自动重试。</p>}
          </div>
        </article>)}
        {!instances.length && <p className="rounded-xl bg-surface p-4 text-[12px] text-fg-3">还没有已连接的 Atlas 实例。</p>}
      </div>
    </section>
    <section className="mt-5 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="路由远程任务">
      <h2 className="m-0 text-[14px] font-semibold">路由任务到远端实例</h2>
      <div className="mt-3 grid gap-2 md:grid-cols-2">
        <label className="grid gap-1 text-[12px] text-fg-2">目标节点<select aria-label="任务目标节点" className={field} value={task.peer_id} onChange={(event) => setTask({ ...task, peer_id: event.target.value })}><option value="">选择节点</option>{peers.map((peer) => <option key={peer.id} value={peer.id}>{peer.name} · {peer.health ?? '待检测'}</option>)}</select></label>
        <input aria-label="远程任务标题" className={field} placeholder="任务名称" value={task.title} onChange={(event) => setTask({ ...task, title: event.target.value })} />
        <input aria-label="远程任务工作区" className={cn(field, 'md:col-span-2')} placeholder="可选：目标节点可访问的绝对工作区路径" value={task.workspace} onChange={(event) => setTask({ ...task, workspace: event.target.value })} />
        <textarea aria-label="远程任务内容" className={cn(field, 'min-h-28 md:col-span-2')} placeholder="任务内容" value={task.content} onChange={(event) => setTask({ ...task, content: event.target.value })} />
      </div>
      <Button className="mt-2" onClick={() => void routeTask()} disabled={busy === 'task' || !peers.length}>{busy === 'task' ? <LoaderCircle size={14} className="spin" /> : null}发送远程任务</Button>
    </section>
    <section className="mt-5 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="离线任务队列">
      <h2 className="m-0 text-[14px] font-semibold">离线队列 · {queue.length}</h2>
      {queue.length ? <ul className="mt-2 grid gap-1.5 pl-5">{queue.map((item) => <li key={item.id} className="text-[11.5px]">{item.title} · {item.status === 'queued' ? '等待节点恢复' : item.status === 'sent' ? '已投递' : '失败'}{item.last_error ? ` · ${item.last_error}` : ''}</li>)}</ul> : <p className="mb-0 mt-2 text-[11.5px] text-fg-3">没有等待投递的远程任务。</p>}
    </section>
    <section className="mt-5 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="集群审计记录">
      <div className="flex items-center gap-2"><h2 className="m-0 flex-1 text-[14px] font-semibold">远程操作审计</h2><Button variant="ghost" onClick={() => void loadAudit()}>查看最近记录</Button></div>
      {auditRows.slice(0, 30).map((row) => <div key={row.id} className="border-t border-line py-1.5 text-[11px] text-fg-3">{new Date(row.time).toLocaleString()} · {row.action} · {row.result}{row.peer_id ? ` · 节点 ${row.peer_id}` : ''}{row.subject_id ? ` · ${row.subject_id}` : ''}</div>)}
      {!auditRows.length && <p className="mb-0 mt-2 text-[11.5px] text-fg-3">令牌轮换、节点登记/撤销、任务路由和远程运行操作会写入本机审计记录，不含令牌或任务正文。</p>}
    </section>
  </div></main>;
}
