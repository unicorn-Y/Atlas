import { useEffect, useState } from 'react';
import { Mic, RefreshCw, Volume2 } from 'lucide-react';

type Device = { deviceId: string; label: string; kind: 'audioinput' | 'audiooutput' };
const INPUT_KEY = 'atlas.audio.input-device';
const OUTPUT_KEY = 'atlas.audio.output-device';

export default function AudioDevicesPanel({ onToast }: { onToast: (message: string) => void }) {
  const [devices, setDevices] = useState<Device[]>([]);
  const [input, setInput] = useState(() => localStorage.getItem(INPUT_KEY) || '');
  const [output, setOutput] = useState(() => localStorage.getItem(OUTPUT_KEY) || '');
  const [error, setError] = useState('');
  const refresh = async () => {
    if (!navigator.mediaDevices?.enumerateDevices) { setError('此设备不支持音频设备枚举。'); return; }
    try {
      const next = await navigator.mediaDevices.enumerateDevices();
      const audio = next.filter((item) => item.kind === 'audioinput' || item.kind === 'audiooutput').map((item) => ({ deviceId: item.deviceId, label: item.label || (item.kind === 'audioinput' ? '未命名麦克风' : '未命名扬声器'), kind: item.kind as Device['kind'] }));
      setDevices(audio); setError(audio.some((item) => item.kind === 'audioinput') ? '' : '没有检测到麦克风。');
    } catch (cause) { setError(cause instanceof Error ? cause.message : '无法读取音频设备。'); }
  };
  useEffect(() => { void refresh(); navigator.mediaDevices?.addEventListener?.('devicechange', refresh); return () => navigator.mediaDevices?.removeEventListener?.('devicechange', refresh); }, []);
  const testInput = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: input ? { deviceId: { exact: input } } : true });
      const track = stream.getAudioTracks()[0];
      onToast(`麦克风已连接：${track.label || '输入设备正常'}`);
      await refresh();
      window.setTimeout(() => stream.getTracks().forEach((item) => item.stop()), 1200);
    } catch (cause) { onToast(`麦克风测试失败：${cause instanceof Error ? cause.message : String(cause)}`); }
  };
  const testOutput = async () => {
    try {
      const context = new AudioContext();
      const routable = context as AudioContext & { setSinkId?: (id: string) => Promise<void> };
      if (output && routable.setSinkId) await routable.setSinkId(output);
      const oscillator = context.createOscillator(); const gain = context.createGain();
      oscillator.frequency.value = 660; gain.gain.value = 0.12; oscillator.connect(gain); gain.connect(context.destination);
      oscillator.start(); oscillator.stop(context.currentTime + 0.25); oscillator.onended = () => { void context.close(); };
      onToast(output && !routable.setSinkId ? '当前运行环境不支持指定输出设备，已使用系统默认扬声器测试。' : '已向所选输出设备播放测试音。');
    } catch (cause) { onToast(`扬声器测试失败：${cause instanceof Error ? cause.message : String(cause)}`); }
  };
  return <section className="grid max-w-[760px] gap-3 rounded-xl border border-line p-4">
    <div className="flex items-center"><h4 className="m-0 flex-1 text-[13.5px] font-medium text-heading">语音设备</h4><button type="button" className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-fg-3 hover:bg-hover" onClick={() => void refresh()}><RefreshCw size={12} />刷新</button></div>
    <label className="grid gap-1 text-[12px] text-fg-2"><span className="inline-flex items-center gap-1.5"><Mic size={13} />输入设备</span><select value={input} onChange={(event) => { setInput(event.target.value); localStorage.setItem(INPUT_KEY, event.target.value); }} className="h-9 rounded-lg border border-line bg-surface px-2 text-[12px]"><option value="">系统默认</option>{devices.filter((item) => item.kind === 'audioinput').map((item) => <option key={item.deviceId} value={item.deviceId}>{item.label}</option>)}</select></label>
    <label className="grid gap-1 text-[12px] text-fg-2"><span className="inline-flex items-center gap-1.5"><Volume2 size={13} />输出设备</span><select value={output} onChange={(event) => { setOutput(event.target.value); localStorage.setItem(OUTPUT_KEY, event.target.value); }} className="h-9 rounded-lg border border-line bg-surface px-2 text-[12px]"><option value="">系统默认</option>{devices.filter((item) => item.kind === 'audiooutput').map((item) => <option key={item.deviceId} value={item.deviceId}>{item.label}</option>)}</select></label>
    <div className="flex gap-2"><button type="button" onClick={() => void testInput()} className="rounded-lg border border-line px-3 py-1.5 text-[11.5px] hover:bg-hover">测试麦克风</button><button type="button" onClick={() => void testOutput()} className="rounded-lg border border-line px-3 py-1.5 text-[11.5px] hover:bg-hover">测试扬声器</button></div>
    {error && <p role="status" className="m-0 text-[11.5px] text-fg-3">{error}</p>}
  </section>;
}
