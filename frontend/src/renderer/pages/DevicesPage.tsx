import { useEffect, useState } from 'react';
import { Laptop, LoaderCircle, Plus, RefreshCw, Smartphone, Trash2 } from 'lucide-react';
import { useAtlasStore } from '../store/useAtlasStore';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';
import TakeoverSection from './devices/TakeoverSection';
import { field } from './agents/shared';

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

  const [form, setForm] = useState({ device_id: '', display_name: '', kind: 'phone', os: '', notes: '' });
  const [busy, setBusy] = useState(false);
  const [confirmId, setConfirmId] = useState('');
  useEffect(() => { void loadDevices(); }, [loadDevices]);
  useEffect(() => {
    const timer = window.setInterval(() => { if (document.visibilityState === 'visible') void loadDevices(); }, 20000);
    return () => window.clearInterval(timer);
  }, [loadDevices]);

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

  return <div className="screen page"><div className="page-inner">
    <header className="page-head">
      <div><h1>设备</h1><p>这台电脑是 Atlas 的身体；其他电脑和手机只作为入口把消息送进来。</p></div>
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
          return <article key={device.id} className="rounded-[14px] bg-surface p-4 shadow-[inset_0_0_0_1px_var(--line)]">
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
          </article>;
        })}
        {!devices.length && !loading && <div className="empty py-10"><Laptop size={20} /><b>还没有登记任何设备</b>本机首次启动时会自动登记为 atlas-laptop。</div>}
      </div>
    </section>

    <section className="mt-6 max-w-[620px]" aria-label="登记入口设备">
      <h2 className="m-0 mb-2 px-1 text-[13.5px] font-semibold text-heading">登记一台入口设备</h2>
      <p className="m-0 mb-3 px-1 text-[12px] leading-[1.6] text-fg-3">手机或另一台电脑想远程指挥 Atlas 时，先在这里登记；它们只能发消息，不能接管这台电脑。</p>
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
