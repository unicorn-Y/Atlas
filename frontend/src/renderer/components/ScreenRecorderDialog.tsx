import { useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../ui/Button';
import { Dialog } from '../ui/Dialog';

const MAX_DURATION_SECONDS = 300;
const MAX_RECORDING_BYTES = 10 * 1024 * 1024;
const MAX_FRAME_RATE = 15;

export default function ScreenRecorderDialog({ open, onClose, onAttach, onToast }: {
  open: boolean; onClose: () => void;
  onAttach: (file: { name: string; mime: string; data_base64: string; size: number }) => void;
  onToast: (message: string) => void;
}) {
  const [active, setActive] = useState(false);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState('');
  const [savedPath, setSavedPath] = useState('');
  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const bytesRef = useRef(0);
  const timerRef = useRef<number | null>(null);
  const videoUrl = useMemo(() => blob ? URL.createObjectURL(blob) : '', [blob]);
  useEffect(() => () => { if (videoUrl) URL.revokeObjectURL(videoUrl); }, [videoUrl]);
  useEffect(() => () => {
    if (timerRef.current !== null) window.clearInterval(timerRef.current);
    recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((track) => track.stop());
  }, []);
  const stop = () => { if (recorderRef.current?.state === 'recording') recorderRef.current.stop(); };
  const start = async () => {
    setError(''); setBlob(null); setSeconds(0); chunksRef.current = []; bytesRef.current = 0;
    if (!navigator.mediaDevices?.getDisplayMedia || typeof MediaRecorder === 'undefined') { setError('当前运行环境不支持屏幕录制。'); return; }
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: { ideal: MAX_FRAME_RATE, max: MAX_FRAME_RATE } }, audio: false });
      streamRef.current = stream;
      const mime = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find((candidate) => MediaRecorder.isTypeSupported(candidate));
      const recorder = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 2_000_000 } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (!event.data.size) return;
        bytesRef.current += event.data.size;
        if (bytesRef.current > MAX_RECORDING_BYTES) { setError('录制已达到 10 MiB 上限，已自动停止。'); stop(); return; }
        chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const result = new Blob(chunksRef.current, { type: recorder.mimeType || 'video/webm' });
        if (result.size) setBlob(result);
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null; setActive(false);
        if (timerRef.current !== null) window.clearInterval(timerRef.current);
        timerRef.current = null;
      };
      stream.getVideoTracks()[0]?.addEventListener('ended', stop, { once: true });
      recorder.start(1000); setActive(true);
      timerRef.current = window.setInterval(() => setSeconds((value) => {
        if (value + 1 >= MAX_DURATION_SECONDS) { window.setTimeout(stop, 0); return MAX_DURATION_SECONDS; }
        return value + 1;
      }), 1000);
    } catch (cause) { setError(`无法开始录制：${cause instanceof Error ? cause.message : String(cause)}`); }
  };
  const save = async () => {
    if (!blob) return;
    if (!window.atlasDesktop?.saveScreenRecording) { setError('当前运行环境没有本机视频保存接口。'); return; }
    try {
      const base64 = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader(); reader.onerror = () => reject(reader.error); reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); reader.readAsDataURL(blob);
      });
      const path = await window.atlasDesktop.saveScreenRecording(base64, `atlas-screen-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`);
      if (path) { setSavedPath(path); onToast(`视频已保存：${path}`); }
    } catch (cause) { setError(`保存视频失败：${cause instanceof Error ? cause.message : String(cause)}`); }
  };
  const attach = async () => {
    if (!blob) return;
    if (blob.size > MAX_RECORDING_BYTES) { setError('视频超过附件大小限制。'); return; }
    const base64 = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader(); reader.onerror = () => reject(reader.error); reader.onload = () => resolve(String(reader.result).split(',')[1] ?? ''); reader.readAsDataURL(blob);
    });
    onAttach({ name: `atlas-screen-${new Date().toISOString().replace(/[:.]/g, '-')}.webm`, mime: blob.type || 'video/webm', data_base64: base64, size: blob.size });
    onClose(); onToast('视频已加入消息附件；发送消息后 Agent 会收到录制文件');
  };
  return <Dialog open={open} onOpenChange={(value) => { if (!value) { if (active) stop(); onClose(); } }} label="屏幕视频录制" className="flex max-h-[88vh] w-[min(850px,94vw)] flex-col bg-panel p-5 shadow-xl">
    <div className="flex items-center gap-3"><h2 className="m-0 text-[16px] font-semibold text-heading">屏幕视频录制</h2><span className="flex-1"/><Button variant="ghost" onClick={() => { if (active) stop(); onClose(); }}>关闭</Button></div>
    <p className="mt-2 text-[12px] text-fg-3">开始时选择要分享的屏幕或窗口。最多 5 分钟、15 fps、10 MiB；视频仅保存在本机，可预览、删除或作为消息附件发送。</p>
    {active && <p role="status" className="m-0 my-2 text-[13px] text-danger">正在录制 · {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')} / 5:00</p>}
    {error && <p role="alert" className="my-2 text-[13px] text-danger">{error}</p>}
    {savedPath && <p className="my-2 break-all text-[11px] text-fg-3">已保存到：{savedPath}</p>}
    {videoUrl && <video className="mt-3 max-h-[55vh] w-full rounded-xl bg-black" controls src={videoUrl} />}
    <div className="mt-4 flex flex-wrap justify-end gap-2">
      {!active && <Button variant="secondary" onClick={() => void start()}>{blob ? '重新录制' : '开始录制'}</Button>}
      {active && <Button variant="primary" onClick={stop}>停止录制</Button>}
      {blob && <><Button variant="secondary" onClick={() => void save()}>保存到本机</Button><Button variant="secondary" onClick={() => {
        if (savedPath && window.atlasDesktop?.deleteScreenRecording) void window.atlasDesktop.deleteScreenRecording(savedPath).then((deleted) => {
          if (deleted) onToast('已删除本机录制文件'); else onToast('本机文件未删除：只能删除本窗口刚保存的录制');
        });
        setSavedPath(''); setBlob(null);
      }}>删除录制</Button><Button variant="primary" onClick={() => void attach()}>作为附件发送给 Agent</Button></>}
    </div>
  </Dialog>;
}
