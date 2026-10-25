import { useEffect, useState } from 'react';
import { Laptop, LoaderCircle, Plus, RefreshCw, Smartphone, Trash2 } from 'lucide-react';
import { api } from '../services/api';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import TakeoverSection from './devices/TakeoverSection';
import { field } from './agents/shared';

interface NodeCapabilityState {
  device_id: string;
  declared: string[];
  pending: string[];
  approved: string[];
  revoked: string[];
  updated_at?: string | null;
  generation: number;
  execution_available: false;
}
interface FileTransferRow { id: string; source_device: string; target_device: string; filename: string; expected_size: number; received_size: number; state: string; expected_sha256: string; expires_at: string; events: Array<{ event: string; actor_device: string; created_at: string }> }

/** 设备页：设备清单（本机 = atlas-laptop，其余是 ingress）+ 控制权 + 交接卡片 + 动态。 */
export default function DevicesPage({ onToast }: { onToast: (text: string) => void }) {
  const devices = useAtlasStore((state) => state.devices);
  const selfDeviceId = useAtlasStore((state) => state.selfDeviceId);
  const loading = useAtlasStore((state) => state.devicesLoading);
  const error = useAtlasStore((state) => state.devicesError);
  const loadDevices = useAtlasStore((state) => state.loadDevices);
  const patchDevice = useAtlasStore((state) => state.patchDevice);
  const removeDevice = useAtlasStore((state) => state.removeDevice);
  const registerDevice = useAtlasStore((state) => state.registerDevice);
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);

  const [form, setForm] = useState({ device_id: '', display_name: '', kind: 'phone', os: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState('');
  const [nodeStates, setNodeStates] = useState<Record<string, NodeCapabilityState>>({});
  const [nodeDrafts, setNodeDrafts] = useState<Record<string, string>>({});
  const [nodeErrors, setNodeErrors] = useState<Record<string, string>>({});
  const [nodeBusy, setNodeBusy] = useState('');
  const [transferRows, setTransferRows] = useState<FileTransferRow[]>([]);
  const [transferTarget, setTransferTarget] = useState('');
  const [transferFile, setTransferFile] = useState<File | null>(null);
  const [transferBusy, setTransferBusy] = useState('');
  const [transferTokens, setTransferTokens] = useState<Record<string, string>>({});
  const nodeDeviceIds = devices.filter((device) => device.kind !== 'atlas-laptop' && device.id !== selfDeviceId).map((device) => device.id).join('\n');
  useEffect(() => { void loadDevices(); }, [loadDevices]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void loadDevices(); }, 20000);
    return () => window.clearInterval(timer);
  }, [loadDevices]);
  useEffect(() => {
    let active = true;
    const ids = nodeDeviceIds ? nodeDeviceIds.split('\n') : [];
    void Promise.all(ids.map(async (id) => {
      try { return [id, await api<NodeCapabilityState>(apiBaseUrl, `/api/devices/${encodeURIComponent(id)}/node-capabilities`)] as const; }
      catch (error) { return [id, error instanceof Error ? error.message : String(error)] as const; }
    })).then((results) => {
      if (!active) return;
      const states: Record<string, NodeCapabilityState> = {};
      const errors: Record<string, string> = {};
      for (const [id, value] of results) {
        if (typeof value === 'string') errors[id] = value;
        else states[id] = value;
      }
      setNodeStates(states);
      setNodeErrors(errors);
      setNodeDrafts((current) => Object.fromEntries(Object.entries(states).map(([id, state]) => [id, current[id] ?? state.declared.join('\n')])));
    });
    return () => { active = false; };
  }, [apiBaseUrl, nodeDeviceIds]);
  const refreshTransfers = async () => {
    const ids = devices.filter((device) => device.trusted).map((device) => device.id);
    const results = await Promise.all(ids.map(async (id) => {
      try { return (await api<{ transfers: FileTransferRow[] }>(apiBaseUrl, `/api/devices/file-transfers?device_id=${encodeURIComponent(id)}`)).transfers; }
      catch { return []; }
    }));
    setTransferRows([...new Map(results.flat().map((row) => [row.id, row])).values()].sort((a, b) => b.expires_at.localeCompare(a.expires_at)));
  };
  useEffect(() => { void refreshTransfers(); }, [apiBaseUrl, nodeDeviceIds, devices.map((device) => `${device.id}:${device.trusted}`).join('|')]);

  const register = async () => {
    setBusy(true);
    const ok = await registerDevice({
      device_id: form.device_id.trim(), display_name: form.display_name.trim() || form.device_id.trim(),
      kind: form.kind, os: form.os.trim(), notes: form.notes.trim(),
    });
    setBusy(false);
    if (ok) { setForm({ device_id: '', display_name: '', kind: 'phone', os: '', notes: '' }); onToast('设备已登记'); }
    else onToast(useAtlasStore.getState().devicesError || '登记失败');
  };

  const updateNodeState = (id: string, state: NodeCapabilityState) => {
    setNodeStates((current) => ({ ...current, [id]: state }));
    setNodeDrafts((current) => ({ ...current, [id]: state.declared.join('\n') }));
    setNodeErrors((current) => ({ ...current, [id]: '' }));
  };

  const saveNodeDeclaration = async (id: string) => {
    setNodeBusy(id);
    try {
      const capabilities = (nodeDrafts[id] ?? '').split(/\r?\n/).map((name) => name.trim()).filter(Boolean);
      const state = await api<NodeCapabilityState>(apiBaseUrl, `/api/devices/${encodeURIComponent(id)}/node-capabilities`, {
        method: 'PUT', json: { capabilities },
      });
      updateNodeState(id, state);
      onToast('节点能力声明已保存；新能力仍需逐项批准');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setNodeBusy('');
  };

  const approveNodeCapability = async (id: string, capability: string) => {
    setNodeBusy(id);
    try {
      const state = await api<NodeCapabilityState>(apiBaseUrl,
        `/api/devices/${encodeURIComponent(id)}/node-capabilities/${encodeURIComponent(capability)}/approve`, { method: 'POST' });
      updateNodeState(id, state);
      onToast(`已明确批准 ${capability} 声明`);
      void loadDevices();
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setNodeBusy('');
  };

  const revokeNodeCapability = async (id: string, capability: string) => {
    setNodeBusy(id);
    try {
      const state = await api<NodeCapabilityState>(apiBaseUrl,
        `/api/devices/${encodeURIComponent(id)}/node-capabilities/${encodeURIComponent(capability)}`, { method: 'DELETE' });
      updateNodeState(id, state);
      onToast(`已撤销 ${capability}`);
      void loadDevices();
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setNodeBusy('');
  };
  const rotateTransferCredential = async (id: string) => {
    setNodeBusy(id);
    try {
      const result = await api<{ token: string }>(apiBaseUrl, `/api/devices/${encodeURIComponent(id)}/file-transfer-credential`, { method: 'POST' });
      setTransferTokens((current) => ({ ...current, [id]: result.token }));
      onToast('新传输令牌已生成；请复制到配对设备，令牌仅显示这一次');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setNodeBusy('');
  };

  const startFileTransfer = async () => {
    if (!transferFile || !transferTarget || !selfDeviceId) return;
    if (transferFile.size > 100 * 1024 * 1024) { onToast('文件最大为 100 MiB'); return; }
    setTransferBusy('create');
    try {
      const digest = await crypto.subtle.digest('SHA-256', await transferFile.arrayBuffer());
      const sha256 = [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
      await api(apiBaseUrl, '/api/devices/file-transfers', { method: 'POST', json: { source_device_id: selfDeviceId, target_device_id: transferTarget, filename: transferFile.name, size: transferFile.size, sha256 } });
      setTransferFile(null);
      await refreshTransfers();
      onToast('已向接收设备创建文件请求；接收方确认后即可开始传输');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setTransferBusy('');
  };
  const acceptTransfer = async (row: FileTransferRow) => {
    setTransferBusy(row.id);
    try {
      await api(apiBaseUrl, `/api/devices/file-transfers/${encodeURIComponent(row.id)}/accept?device_id=${encodeURIComponent(row.target_device)}`, { method: 'POST' });
      await refreshTransfers();
      onToast('接收设备已确认；发送端可以开始上传');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setTransferBusy('');
  };
  const uploadTransfer = async (row: FileTransferRow) => {
    if (!transferFile || row.source_device !== selfDeviceId || transferFile.name !== row.filename || transferFile.size !== row.expected_size) { onToast('请重新选择与请求文件同名且大小一致的文件'); return; }
    setTransferBusy(row.id);
    try {
      const chunkBytes = 1024 * 1024;
      for (let offset = 0; offset < transferFile.size; offset += chunkBytes) {
        const chunk = transferFile.slice(offset, Math.min(offset + chunkBytes, transferFile.size));
        await api(apiBaseUrl, `/api/devices/file-transfers/${encodeURIComponent(row.id)}/chunks/${offset}?device_id=${encodeURIComponent(row.source_device)}`, { method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: chunk });
        await refreshTransfers();
      }
      onToast('文件已上传并通过 SHA-256 校验，等待接收端取回');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setTransferBusy('');
  };
  const cancelTransfer = async (row: FileTransferRow) => {
    setTransferBusy(row.id);
    try {
      const actor = row.source_device === selfDeviceId ? row.source_device : row.target_device;
      await api(apiBaseUrl, `/api/devices/file-transfers/${encodeURIComponent(row.id)}/cancel?device_id=${encodeURIComponent(actor)}`, { method: 'POST' });
      await refreshTransfers();
      onToast('文件传输已取消');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setTransferBusy('');
  };
  const downloadTransfer = async (row: FileTransferRow) => {
    setTransferBusy(row.id);
    try {
      const response = await fetch(`${apiBaseUrl}/api/devices/file-transfers/${encodeURIComponent(row.id)}/download?device_id=${encodeURIComponent(row.target_device)}`);
      if (!response.ok) throw new Error(`下载失败：HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = row.filename; anchor.click(); URL.revokeObjectURL(url);
      await refreshTransfers();
      onToast('文件已保存到浏览器下载目录');
    } catch (error) { onToast(error instanceof Error ? error.message : String(error)); }
    setTransferBusy('');
  };

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>设备</h1><p>管理本机和可信配对设备；远程设备可按已批准能力接收文件传输，其他远程执行能力仍未开放。</p></div>
      <div className="btns">
        <button className="btn ghost" onClick={() => void loadDevices()} disabled={loading} aria-label="刷新设备">{loading ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />}</button>
      </div>
    </header>

    {error && <div className="error-note" role="alert">{error}</div>}

    <TakeoverSection selfDeviceId={selfDeviceId} onToast={onToast} />

    <section className="mt-6" aria-label="设备列表">
      <h2 className="m-0 mb-2 px-1 text-[13.5px] font-semibold text-heading">设备清单</h2>
      <div className="grid gap-2 sm:grid-cols-2">
        {devices.map((device) => {
          const self = device.id === selfDeviceId || device.kind === 'atlas-laptop';
          const online = Boolean(device.online);
          return <article key={device.id} className="rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]">
            <header className="flex items-center gap-2.5">
              {self ? <Laptop size={17} className="shrink-0 text-brand" /> : <Smartphone size={17} className="shrink-0 text-fg-3" />}
              <b className="min-w-0 truncate text-[14px] font-medium text-fg">{device.display_name}</b>
              {self && <span className="shrink-0 rounded-full bg-brand-soft px-2 py-0.5 text-[11px] text-fg">本机 · atlas-laptop</span>}
              <span className="flex-1" />
              <span className={cn('flex shrink-0 items-center gap-1 text-[12px]', online ? 'text-ok' : 'text-fg-3')}>
                <i className={cn('size-1.5 rounded-full', online ? 'bg-ok' : 'bg-current')} />{online ? '在线' : '离线'}
              </span>
            </header>
            <p className="mb-2 mt-1.5 text-[12.5px] leading-[1.6] text-fg-3">
              {device.kind}{device.os ? ` · ${device.os}` : ''}{device.notes ? ` · ${device.notes}` : ''}
              {device.presence?.activity ? ` · 正在：${device.presence.activity}` : ''}
            </p>
            <div className="flex items-center gap-2.5">
              <label className="flex items-center gap-1.5 text-[12.5px] text-fg-2">
                <input type="checkbox" checked={Boolean(device.trusted)} disabled={self}
                  onChange={(event) => void patchDevice(device.id, { trusted: event.target.checked }).then(() => onToast('已更新'))} />
                信任这台设备
              </label>
              <span className="flex-1" />
              {!self && <Button size="sm" variant={confirmId === device.id ? 'danger' : 'ghost'}
                onClick={() => { if (confirmId !== device.id) { setConfirmId(device.id); return; } setConfirmId(''); void removeDevice(device.id).then(() => onToast('设备已移除')); }}>
                <Trash2 />{confirmId === device.id ? '确认移除' : '移除'}
              </Button>}
            </div>
            {!self && <div className="mt-3 border-t border-line pt-3" aria-label={`${device.display_name}节点能力审批`}>
              <div className="flex items-center gap-2 text-[12.5px]">
                <b className="font-medium text-fg">节点能力声明</b>
                <span className="flex-1" />
                {nodeStates[device.id] && <span className="text-fg-3">generation {nodeStates[device.id].generation}</span>}
              </div>
              <p className="mb-2 mt-1 text-[11.5px] leading-[1.5] text-fg-3">能力声明是待审的登记信息；批准 files.send / files.receive 后，可信节点才可参与配对文件传输。其他能力当前仍没有远程节点执行 runtime。</p>
              {nodeErrors[device.id]
                ? <p role="alert" className="m-0 text-[12px] text-danger">无法读取节点能力：{nodeErrors[device.id]}</p>
                : <>
                  <label className="grid gap-1 text-[11.5px] text-fg-3">每行一个能力标识
                    <textarea rows={2} value={nodeDrafts[device.id] ?? ''}
                      onChange={(event) => setNodeDrafts((current) => ({ ...current, [device.id]: event.target.value }))}
                      placeholder={'files.send\nfiles.receive'} className={cn(field, 'min-h-14 resize-y font-mono text-[12px]')} />
                  </label>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <Button size="sm" variant="secondary" disabled={nodeBusy === device.id}
                      onClick={() => void saveNodeDeclaration(device.id)}>保存声明</Button>
                    {nodeBusy === device.id && <LoaderCircle size={13} className="spin text-fg-3" />}
                  </div>
                  {nodeStates[device.id]?.pending.map((capability) => <div key={`pending:${capability}`} className="mt-2 flex items-center gap-2 text-[12px]">
                    <span className="text-fg-2">待批准：<code>{capability}</code></span><span className="flex-1" />
                    <Button size="sm" variant="secondary" disabled={nodeBusy === device.id}
                      onClick={() => void approveNodeCapability(device.id, capability)}>明确批准</Button>
                  </div>)}
                  {nodeStates[device.id]?.approved.map((capability) => <div key={`approved:${capability}`} className="mt-2 flex items-center gap-2 text-[12px]">
                    <span className="text-ok">已批准：<code>{capability}</code></span><span className="flex-1" />
                    <Button size="sm" variant="ghost" disabled={nodeBusy === device.id}
                      onClick={() => void revokeNodeCapability(device.id, capability)}>撤销</Button>
                  </div>)}
                  {nodeStates[device.id]?.revoked.map((capability) => <div key={`revoked:${capability}`} className="mt-2 flex items-center gap-2 text-[12px]">
                    <span className="text-fg-3">已撤销：<code>{capability}</code></span><span className="flex-1" />
                    <Button size="sm" variant="ghost" disabled={nodeBusy === device.id}
                      onClick={() => void approveNodeCapability(device.id, capability)}>重新批准</Button>
                  </div>)}
                  <div className="mt-2 border-t border-line pt-2">
                    <Button size="sm" variant="secondary" disabled={nodeBusy === device.id || !device.trusted} onClick={() => void rotateTransferCredential(device.id)}>生成 / 轮换传输令牌</Button>
                    {transferTokens[device.id] && <label className="mt-2 grid gap-1 text-[11px] text-fg-3">一次性传输令牌（请安全复制到配对设备；轮换会立即使旧令牌失效）<textarea readOnly rows={2} value={transferTokens[device.id]} onFocus={(event) => event.currentTarget.select()} className={cn(field, 'font-mono text-[11px]')} /></label>}
                  </div>
                </>}
            </div>}
          </article>;
        })}
        {!devices.length && !loading && <div className="empty py-10"><Laptop size={20} /><b>还没有登记任何设备</b>本机首次启动时会自动登记为 atlas-laptop。</div>}
      </div>
    </section>

    <section className="mt-6 rounded-xl bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]" aria-label="设备文件传输">
      <h2 className="m-0 text-[13.5px] font-semibold text-heading">配对设备文件传输</h2>
      <p className="mb-3 mt-1 text-[11.5px] leading-[1.55] text-fg-3">接收设备需可信并批准 <code>files.receive</code>，发送节点需批准 <code>files.send</code>；单文件最大 100 MiB，1 MiB 分块上传，SHA-256 完整性校验，请求 24 小时过期。接收确认后开始传输。</p>
      <div className="flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-[12px]">接收设备<select className={field} value={transferTarget} onChange={(event) => setTransferTarget(event.target.value)}><option value="">选择已批准接收能力的设备</option>{devices.filter((device) => device.id !== selfDeviceId && device.trusted && nodeStates[device.id]?.approved.includes('files.receive')).map((device) => <option key={device.id} value={device.id}>{device.display_name} · {device.id}</option>)}</select></label>
        <label className="grid gap-1 text-[12px]">文件<input type="file" onChange={(event) => setTransferFile(event.target.files?.[0] ?? null)} /></label>
        <Button variant="primary" disabled={transferBusy === 'create' || !transferFile || !transferTarget} onClick={() => void startFileTransfer()}>{transferBusy === 'create' ? '准备中…' : '请求发送'}</Button>
        <Button variant="ghost" onClick={() => void refreshTransfers()}>刷新传输</Button>
      </div>
      <div className="mt-3 grid gap-2">{transferRows.map((row) => <article key={row.id} className="rounded-lg bg-sunken p-3 text-[12px]"><div className="flex flex-wrap items-center gap-2"><b className="text-fg">{row.filename}</b><code>{row.id.slice(0, 10)}</code><span className="text-fg-3">{row.state}</span><span className="flex-1 text-right tabular-nums text-fg-3">{row.received_size}/{row.expected_size} bytes · {Math.floor(row.received_size / row.expected_size * 100)}%</span></div><div className="mt-1 h-1.5 overflow-hidden rounded bg-line"><div className="h-full bg-brand" style={{ width: `${Math.floor(row.received_size / row.expected_size * 100)}%` }} /></div><div className="mt-2 flex flex-wrap items-center gap-1.5">{row.state === 'awaiting_confirmation' && row.target_device === selfDeviceId && <Button size="sm" variant="secondary" disabled={transferBusy === row.id} onClick={() => void acceptTransfer(row)}>接收并授权</Button>}{row.state === 'uploading' && row.source_device === selfDeviceId && <Button size="sm" variant="secondary" disabled={transferBusy === row.id || !transferFile || transferFile.name !== row.filename || transferFile.size !== row.expected_size} onClick={() => void uploadTransfer(row)}>上传文件分块</Button>}{row.state === 'ready' && row.target_device === selfDeviceId && <Button size="sm" variant="secondary" disabled={transferBusy === row.id} onClick={() => void downloadTransfer(row)}>下载并完成</Button>}{['awaiting_confirmation', 'uploading', 'ready'].includes(row.state) && <Button size="sm" variant="ghost" disabled={transferBusy === row.id} onClick={() => void cancelTransfer(row)}>取消</Button>}<span className="flex-1" /><span className="text-[10px] text-fg-3">SHA-256 {row.expected_sha256.slice(0, 16)}… · 到期 {new Date(row.expires_at).toLocaleString()}</span></div><p className="mb-0 mt-1 text-[10px] text-fg-3">审计：{row.events.map((event) => `${event.event}/${event.actor_device}`).join(' → ')}</p></article>)}{!transferRows.length && <span className="text-[11px] text-fg-3">当前没有文件传输请求</span>}</div>
    </section>

    <section className="mt-6 max-w-[620px]" aria-label="登记入口设备">
      <h2 className="m-0 mb-2 px-1 text-[13.5px] font-semibold text-heading">登记一台入口设备</h2>
      <p className="m-0 mb-3 px-1 text-[12px] leading-[1.6] text-fg-3">登记设备后可单独标记为可信，并逐项审批文件传输能力；登记本身不会开放远程执行。</p>
      <form className="grid gap-2.5" onSubmit={(event) => { event.preventDefault(); void register(); }}>
        <div className="grid grid-cols-2 gap-2.5">
          <label className="grid gap-1 text-[12.5px] text-fg-2">设备 ID
            <input required value={form.device_id} onChange={(event) => setForm({ ...form, device_id: event.target.value })}
              placeholder="my-phone" className={cn(field, 'font-mono text-[12.5px]')} />
          </label>
          <label className="grid gap-1 text-[12.5px] text-fg-2">显示名
            <input value={form.display_name} onChange={(event) => setForm({ ...form, display_name: event.target.value })}
              placeholder="我的手机" className={field} />
          </label>
        </div>
        <div className="grid grid-cols-2 gap-2.5">
          <label className="grid gap-1 text-[12.5px] text-fg-2">类型
            <select value={form.kind} onChange={(event) => setForm({ ...form, kind: event.target.value })} className={field}>
              <option value="phone">手机</option>
              <option value="laptop">电脑（ingress）</option>
              <option value="ingress">其他入口</option>
            </select>
          </label>
          <label className="grid gap-1 text-[12.5px] text-fg-2">系统
            <input value={form.os} onChange={(event) => setForm({ ...form, os: event.target.value })} placeholder="iOS 19" className={field} />
          </label>
        </div>
        <div className="flex items-center gap-2">
          <Button type="submit" variant="primary" disabled={busy || !form.device_id.trim()}><Plus />登记</Button>
          {busy && <LoaderCircle size={15} className="spin text-fg-3" />}
        </div>
      </form>
    </section>
  </div></div>;
}
