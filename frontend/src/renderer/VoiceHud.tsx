import { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { AudioLines, Mic, Square } from 'lucide-react';
import { getSelectedInputStream } from './services/audioDevices';
import { initialHudState, reduceHudMessage, type HudStatus } from './services/voiceHudProtocol';
import './voice-hud.css';

function VoiceHud() {
  const [status, setStatus] = useState<HudStatus>('idle');
  const [detail, setDetail] = useState('快捷键开始语音输入');
  const [transcript, setTranscript] = useState('');
  const [level, setLevel] = useState(0);
  const finalTranscriptRef = useRef('');
  const hudStateRef = useRef(initialHudState());
  const sessionRef = useRef<{ socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode; silent: GainNode } | null>(null);
  const startRef = useRef<() => void>(() => undefined);
  const stop = useCallback(() => {
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      try { if (session.socket.readyState === WebSocket.OPEN) session.socket.send(JSON.stringify({ type: 'end' })); session.socket.close(); } catch { /* socket already closed */ }
      session.processor.disconnect(); session.silent.disconnect(); session.stream.getTracks().forEach((track) => track.stop()); void session.context.close();
    }
    setLevel(0); setStatus('idle'); setDetail('快捷键开始语音输入');
    hudStateRef.current = initialHudState(); finalTranscriptRef.current = '';
  }, []);
  const start = useCallback(async () => {
    if (sessionRef.current) return;
    setStatus('connecting'); setDetail('正在连接本地语音识别…'); setTranscript(''); finalTranscriptRef.current = '';
    hudStateRef.current = { ...initialHudState(), status: 'connecting', detail: '正在连接本地语音识别…' };
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    try {
      const input = await getSelectedInputStream({ channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true });
      stream = input.stream;
      if (input.usedFallback) setDetail('麦克风已断开，已回落系统默认输入。正在连接…');
      context = new AudioContext();
      const source = context.createMediaStreamSource(stream);
      const processor = context.createScriptProcessor(4096, 1, 1);
      const silent = context.createGain(); silent.gain.value = 0;
      const url = new URL('/ws/asr', window.atlasDesktop?.apiBaseUrl ?? 'http://127.0.0.1:8765'); url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(url);
      const session = { socket, stream, context, processor, silent };
      sessionRef.current = session;
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(String(event.data)) as { type?: string; text?: string; detail?: string; progress?: number };
          const next = reduceHudMessage(hudStateRef.current, message);
          hudStateRef.current = next;
          finalTranscriptRef.current = next.committedTranscript;
          setStatus(next.status); setDetail(next.detail); setTranscript(next.transcript);
          if (message.type === 'error') stop(), setStatus('error'), setDetail(message.detail || '语音识别失败');
        } catch { /* ignore malformed ASR response */ }
      };
      socket.onerror = () => { stop(); setStatus('error'); setDetail('本地语音识别连接失败'); };
      socket.onclose = () => {
        if (sessionRef.current === session) {
          sessionRef.current = null; processor.disconnect(); silent.disconnect(); stream?.getTracks().forEach((track) => track.stop()); void context?.close();
          setStatus('error'); setDetail('语音识别连接已断开，请重试。');
        }
      };
      stream.getAudioTracks()[0]?.addEventListener('ended', () => {
        if (sessionRef.current === session) { stop(); setStatus('error'); setDetail('麦克风已断开，请连接设备后重试。'); }
      }, { once: true });
      await new Promise<void>((resolve, reject) => { socket.addEventListener('open', () => resolve(), { once: true }); socket.addEventListener('error', () => reject(new Error('本地语音识别连接失败')), { once: true }); });
      processor.onaudioprocess = (event) => {
        if (socket.readyState !== WebSocket.OPEN) return;
        const inputData = event.inputBuffer.getChannelData(0);
        let energy = 0; for (const value of inputData) energy += value * value;
        setLevel(Math.min(1, Math.sqrt(energy / inputData.length) * 7));
        const ratio = context!.sampleRate / 16000;
        const samples = ratio <= 1 ? inputData : Float32Array.from({ length: Math.floor(inputData.length / ratio) }, (_, index) => inputData[Math.floor(index * ratio)]);
        const pcm = new Int16Array(samples.length);
        for (let index = 0; index < samples.length; index++) pcm[index] = Math.max(-1, Math.min(1, samples[index])) * 0x7fff;
        socket.send(pcm.buffer);
      };
      source.connect(processor); processor.connect(silent); silent.connect(context.destination);
      setStatus('preparing'); setDetail(input.usedFallback ? '麦克风已断开，使用系统默认输入；正在准备模型…' : '正在准备本地语音模型…');
    } catch (cause) {
      const session = sessionRef.current; sessionRef.current = null;
      try { session?.socket.close(); session?.processor.disconnect(); session?.silent.disconnect(); } catch { /* already closed */ }
      stream?.getTracks().forEach((track) => track.stop()); void context?.close();
      setStatus('error'); setDetail(cause instanceof Error ? cause.message : String(cause));
    }
  }, [stop]);
  startRef.current = () => { void start(); };
  useEffect(() => {
    const offStart = window.atlasDesktop?.onVoiceHudStart?.(() => startRef.current());
    const offStop = window.atlasDesktop?.onVoiceHudStop?.(stop);
    startRef.current();
    return () => { offStart?.(); offStop?.(); stop(); };
  }, [stop]);
  return <main className="voice-hud" aria-label="Atlas 语音输入">
    <div className="hud-pill">
    <div className="hud-mark"><AudioLines size={17} /><span>Atlas</span></div>
    <div className="hud-state"><b>{status === 'listening' ? '正在聆听' : status === 'preparing' ? '准备语音' : status === 'connecting' ? '正在连接' : status === 'error' ? '语音不可用' : '语音输入'}</b><span>{detail}</span></div>
    <div className="hud-wave" aria-label={`麦克风音量 ${Math.round(level * 100)}%`}>
      {Array.from({ length: 13 }, (_, index) => <i key={index} style={{ height: `${5 + Math.round(level * (9 + (index % 4) * 4))}px` }} />)}
    </div>
    <div className="hud-text" aria-live="polite" title={transcript}>{transcript || '转写内容会显示在这里'}</div>
    <div className="hud-spacer" aria-hidden="true" />
    {status === 'error' && <button type="button" className="hud-retry" title="重试语音输入" onClick={() => { void start(); }}><Mic size={15} /></button>}
    <button type="button" className="hud-stop" title="停止语音输入" aria-label="停止语音输入" onClick={stop}><Square size={14} fill="currentColor" /></button>
    <span className="hud-grip" title="拖动定位" aria-hidden="true">⋮⋮</span>
    </div>
  </main>;
}

createRoot(document.getElementById('root')!).render(<VoiceHud />);
