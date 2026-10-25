import { useCallback, useEffect, useState } from 'react';
import { api } from '../../services/api';
import { Empty } from './Empty';

interface Device { serial: string; state: string; model?: string; product?: string; transport_id?: string }
interface DeviceList { devices: Device[]; avds: string[]; available: boolean; reason?: string }
interface Frame { serial: string; captured_at: string; data_url: string }

export default function AndroidEmulatorPanel({ apiBaseUrl, workspace, connected }: { apiBaseUrl: string; workspace?: string | null; connected: boolean }) {
  const [deviceInfo, setDeviceInfo] = useState<DeviceList | null>(null);
  const [serial, setSerial] = useState('');
  const [avd, setAvd] = useState('');
  const [frame, setFrame] = useState<Frame | null>(null);
  const [apk, setApk] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [autoRefresh, setAutoRefresh] = useState(false);
  const loadDevices = useCallback(async () => {
    const result = await api<DeviceList>(apiBaseUrl, '/api/mobile/android/devices');
    setDeviceInfo(result);
    setAvd((current) => current || result.avds[0] || '');
    setSerial((current) => result.devices.some((device) => device.serial === current && device.state === 'device')
      ? current : result.devices.find((device) => device.state === 'device')?.serial ?? '');
  }, [apiBaseUrl]);
  const capture = useCallback(async (target = serial) => {
    if (!target) return;
    try { setError(''); setFrame(await api<Frame>(apiBaseUrl, `/api/mobile/android/screenshot?${new URLSearchParams({ serial: target })}`)); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
  }, [apiBaseUrl, serial]);
  useEffect(() => {
    if (!connected) return;
    let stale = false;
    api<DeviceList>(apiBaseUrl, '/api/mobile/android/devices').then((result) => {
      if (stale) return; setDeviceInfo(result); setAvd(result.avds[0] ?? '');
      setSerial(result.devices.find((device) => device.state === 'device')?.serial ?? '');
    }).catch((exc) => { if (!stale) setError(exc instanceof Error ? exc.message : String(exc)); });
    return () => { stale = true; };
  }, [connected, apiBaseUrl]);
  useEffect(() => { if (!autoRefresh || !serial) return; const timer = window.setInterval(() => { void capture(serial); }, 2000); return () => window.clearInterval(timer); }, [autoRefresh, serial, capture]);
  const start = async () => {
    if (!avd || busy) return;
    setBusy('start'); setError(''); setNotice('正在启动模拟器并等待 Android 就绪…');
    try { const result = await api<{ serial?: string }>(apiBaseUrl, '/api/mobile/android/start', { method: 'POST', json: { avd } });
      await loadDevices(); const target = result.serial ?? ''; if (target) setSerial(target); setNotice(`模拟器已就绪${target ? `：${target}` : ''}`); if (target) await capture(target);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); setNotice(''); }
    finally { setBusy(''); }
  };
  const install = async () => {
    if (!workspace || !serial || !apk.trim() || busy) return;
    setBusy('install'); setError(''); setNotice('正在向所选设备安装 APK…');
    try { const result = await api<{ serial: string; apkPath: string }>(apiBaseUrl, '/api/mobile/android/install', { method: 'POST', json: { workspace, serial, apkPath: apk.trim() } }); setNotice(`已安装到 ${result.serial}：${result.apkPath}`); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); setNotice(''); }
    finally { setBusy(''); }
  };
  if (!connected) return <Empty title="后端未连接" body="连接 Atlas 后端后可查看 Android 模拟器。" />;
  return <section aria-label="Android 模拟器嵌入预览" className="grid gap-3">
    <div className="grid gap-2 rounded-xl card-surface p-3">
      <div className="flex flex-wrap items-end gap-2"><label className="min-w-40 flex-1 text-[12px] text-fg-2">已连接的 Android 设备<select aria-label="Android 模拟器设备" value={serial} onChange={(event) => { setSerial(event.target.value); setFrame(null); }} className="mt-1 h-9 w-full rounded-lg bg-sunken px-2 text-[12px] text-fg"><option value="">选择设备</option>{deviceInfo?.devices.map((device) => <option key={device.serial} value={device.serial} disabled={device.state !== 'device'}>{device.serial} · {device.model || device.state}</option>)}</select></label><button type="button" onClick={() => void loadDevices().catch((exc) => setError(exc instanceof Error ? exc.message : String(exc)))} className="h-9 rounded-lg px-3 text-[12px] text-fg-2 hover:bg-hover">刷新设备</button><button type="button" disabled={!serial || busy === 'start'} onClick={() => void capture()} className="h-9 rounded-lg bg-brand-soft px-3 text-[12px] text-fg">刷新画面</button><label className="flex h-9 items-center gap-1.5 px-2 text-[12px] text-fg-2"><input type="checkbox" checked={autoRefresh} onChange={(event) => setAutoRefresh(event.target.checked)} />每 2 秒刷新</label></div>
      {deviceInfo?.avds.length ? <div className="flex flex-wrap gap-2"><label className="min-w-40 flex-1 text-[12px] text-fg-2">启动 AVD<select aria-label="Android AVD" value={avd} onChange={(event) => setAvd(event.target.value)} className="mt-1 h-9 w-full rounded-lg bg-sunken px-2 text-[12px] text-fg">{deviceInfo.avds.map((name) => <option key={name}>{name}</option>)}</select></label><button type="button" disabled={!avd || Boolean(busy)} onClick={() => void start()} className="h-9 self-end rounded-lg bg-brand-soft px-3 text-[12px] text-fg">{busy === 'start' ? '正在启动…' : '启动并预览'}</button></div> : <p className="m-0 text-[12px] text-fg-3">{deviceInfo?.reason ?? '没有可用的 AVD；连接已启动的 Android 模拟器，或安装 Android SDK 并创建 AVD。'}</p>}
      {workspace && <div className="flex flex-wrap items-end gap-2"><label className="min-w-40 flex-1 text-[12px] text-fg-2">在工作区安装 APK<input aria-label="APK 相对路径" value={apk} onChange={(event) => setApk(event.target.value)} placeholder="例如 app/build/outputs/apk/debug/app-debug.apk" className="mt-1 h-9 w-full rounded-lg bg-sunken px-2 text-[12px] text-fg" /></label><button type="button" disabled={!serial || !apk.trim() || Boolean(busy)} onClick={() => void install()} className="h-9 rounded-lg px-3 text-[12px] text-fg-2 hover:bg-hover">{busy === 'install' ? '正在安装…' : '安装到所选设备'}</button></div>}
    </div>
    {error && <p role="alert" className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">操作失败：{error}</p>}{notice && <p role="status" className="m-0 text-[12px] text-fg-3">{notice}</p>}
    {frame ? <figure className="m-0 overflow-hidden rounded-xl border border-line bg-black"><img src={frame.data_url} alt={`Android 模拟器 ${frame.serial} 当前画面`} className="mx-auto max-h-[70vh] max-w-full object-contain" /><figcaption className="bg-panel px-3 py-2 text-[11px] text-fg-3">{frame.serial} · {new Date(frame.captured_at).toLocaleTimeString()}</figcaption></figure> : <Empty title={serial ? '还没有画面' : '选择或启动模拟器'} body={serial ? '点击“刷新画面”读取设备当前显示。' : '选择一个已连接设备，或启动列表中的 AVD。'} />}
  </section>;
}
