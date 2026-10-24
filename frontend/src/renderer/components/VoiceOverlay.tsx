import { useCallback, useEffect, useRef, useState } from 'react';
import { Captions, MessageSquareText, MicOff, PhoneOff, Hand, RotateCcw } from 'lucide-react';
import { api } from '../services/api';

type Phase = 'listening' | 'thinking' | 'speaking' | 'paused' | 'unavailable';

interface VoiceOverlayProps {
  apiBaseUrl: string;
  onClose: (toChat: boolean) => void;
  onSend: (text: string) => void;
  /** id of the run currently shown in the conversation */
  runId: string | null;
  /** assistant text streamed by that run so far */
  reply: string;
  runDone: boolean;
  modelName: string;
  speechVoice?: string;
  speechVoices?: SpeechSynthesisVoice[];
  onSpeechVoiceChange?: (voice: string) => void;
}

const SENTENCE = /[。！？.!?；;\n]/;
export function classifyVoiceFailure(cause: unknown): { category: string; detail: string; next: string } {
  const error = cause as { name?: string; message?: string };
  const name = error?.name ?? '';
  const detail = error?.message || (typeof cause === 'string' ? cause : '语音服务发生未知错误');
  if (name === 'NotAllowedError' || name === 'SecurityError') return { category: '麦克风权限被拒绝', detail, next: '在系统设置中允许 Atlas 使用麦克风，然后重试。' };
  if (name === 'NotFoundError' || name === 'OverconstrainedError' || name === 'NotReadableError' || name === 'AbortError' || /device.*not found|no.*microphone|设备.*不可用|没有.*麦克风|设备.*断开/i.test(detail)) return { category: '麦克风设备不可用', detail, next: '连接麦克风，或在音频设置中选择可用设备。' };
  if (/模型|model|download|未准备|not ready/i.test(detail)) return { category: '语音模型缺失', detail, next: '先在语音设置中下载本地识别模型。' };
  if (/pcm|音频帧|格式|decode|解码|invalid audio/i.test(detail)) return { category: '音频格式或解码失败', detail, next: '检查麦克风输入格式后重新连接。' };
  if (/websocket|socket|network|fetch|连接|断开|1011|1006/i.test(detail)) return { category: '语音网络或后端断连', detail, next: '检查 Atlas 后端连接后重试。' };
  return { category: '语音启动失败', detail, next: '检查麦克风和 Atlas 语音服务后重试，或转为文字。' };
}
export default function VoiceOverlay({ apiBaseUrl, onClose, onSend, runId, reply, runDone, modelName, speechVoice = '', speechVoices = [], onSpeechVoiceChange }: VoiceOverlayProps) {
  const [phase, setPhase] = useState<Phase>('listening');
  const [heard, setHeard] = useState('');
  const [said, setSaid] = useState('');
  const [captions, setCaptions] = useState(true);
  const [muted, setMuted] = useState(false);
  const [problem, setProblem] = useState('');
  const [seconds, setSeconds] = useState(0);
  const orbRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<{ socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode; silent: GainNode } | null>(null);
  const levelRef = useRef(0);
  const phaseRef = useRef<Phase>('listening');
  const mutedRef = useRef(false);
  const staleRunRef = useRef<string | null>(runId);
  const trackedRunRef = useRef<string | null>(null);
  const spokenRef = useRef(0);
  const pendingRef = useRef(0);
  const doneRef = useRef(false);
  const failureRef = useRef(0);
  const speechFramesRef = useRef(0);
  const utteranceAcceptedRef = useRef(false);
  phaseRef.current = phase;
  mutedRef.current = muted;

  const listen = useCallback(() => {
    if (mutedRef.current) { setPhase('paused'); return; }
    if (recognitionRef.current && recognitionRef.current.socket.readyState <= WebSocket.OPEN) return;
    void (async () => {
      try {
        const status = await api<{ ready: boolean; message?: string }>(apiBaseUrl, '/api/asr/status');
        if (!status.ready) { setProblem(status.message || '请先准备本地语音识别模型。'); setPhase('unavailable'); return; }
        const inputDevice = localStorage.getItem('atlas.audio.input-device') || '';
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { ...(inputDevice ? { deviceId: { exact: inputDevice } } : {}), channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const processor = context.createScriptProcessor(4096, 1, 1);
        const silent = context.createGain(); silent.gain.value = 0;
        const socketUrl = new URL('/ws/asr', apiBaseUrl); socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(socketUrl);
        const session = { socket, stream, context, processor, silent };
        recognitionRef.current = session;
        const connectedAt = Date.now();
        socket.onmessage = (event) => {
          try {
            const message = JSON.parse(String(event.data)) as { type?: string; text?: string; detail?: string };
            if (message.type === 'partial') setHeard(message.text || '');
            if (message.type === 'final' && message.text?.trim() && !utteranceAcceptedRef.current && (phaseRef.current === 'listening' || phaseRef.current === 'speaking')) {
              utteranceAcceptedRef.current = true;
              setHeard(message.text.trim());
              if (phaseRef.current === 'speaking') window.speechSynthesis?.cancel();
              pendingRef.current = 0;
              staleRunRef.current = trackedRunRef.current ?? runIdRef.current; trackedRunRef.current = null;
              setSaid(''); setPhase('thinking'); onSendRef.current(message.text.trim());
            }
            if (message.type === 'error') {
              const failure = classifyVoiceFailure(message.detail); setProblem(`${failure.category}：${failure.detail}。${failure.next}`); setPhase('unavailable');
              if (recognitionRef.current === session) recognitionRef.current = null;
              try { if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'end' })); socket.close(); } catch { /* already closing */ }
              processor.disconnect(); silent.disconnect(); stream.getTracks().forEach((track) => track.stop()); void context.close();
            }
          } catch { /* malformed local ASR response */ }
        };
        socket.onerror = () => { const failure = classifyVoiceFailure('WebSocket 连接失败'); setProblem(`${failure.category}：${failure.detail}。${failure.next}`); };
        socket.onclose = (event) => {
          const isCurrent = recognitionRef.current?.socket === socket;
          if (isCurrent) {
            recognitionRef.current = null;
            processor.disconnect(); silent.disconnect(); stream.getTracks().forEach((track) => track.stop()); void context.close();
          }
          if (Date.now() - connectedAt > 30_000) failureRef.current = 0;
          if (isCurrent && !mutedRef.current && event.code !== 1000 && failureRef.current < 2) {
            failureRef.current += 1;
            setPhase('thinking');
            window.setTimeout(() => { if (!mutedRef.current && !recognitionRef.current) listen(); }, 350 * failureRef.current);
          } else if (isCurrent && !mutedRef.current && event.code !== 1000) {
            const failure = classifyVoiceFailure('WebSocket 语音连接中断'); setProblem(`${failure.category}：${failure.detail}。已重连 2 次仍未恢复。${failure.next}`); setPhase('unavailable');
          }
        };
        await new Promise<void>((resolve, reject) => { socket.addEventListener('open', () => resolve(), { once: true }); socket.addEventListener('error', () => reject(new Error('本地语音识别连接失败')), { once: true }); });
        const downsample = (samples: Float32Array, from: number) => {
          if (from <= 16000) return samples;
          const ratio = from / 16000; const output = new Float32Array(Math.floor(samples.length / ratio));
          for (let i = 0; i < output.length; i++) output[i] = samples[Math.floor(i * ratio)];
          return output;
        };
        processor.onaudioprocess = (event) => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const input = event.inputBuffer.getChannelData(0);
          let power = 0; for (const sample of input) power += sample * sample;
          const voiced = Math.sqrt(power / input.length) > 0.018;
          speechFramesRef.current = voiced ? speechFramesRef.current + 1 : 0;
          if (speechFramesRef.current >= 3 && phaseRef.current === 'speaking') {
            window.speechSynthesis?.cancel(); pendingRef.current = 0; utteranceAcceptedRef.current = false;
            staleRunRef.current = trackedRunRef.current ?? runIdRef.current; trackedRunRef.current = null;
            setSaid(''); setPhase('listening');
          } else if (speechFramesRef.current >= 3 && phaseRef.current === 'listening') utteranceAcceptedRef.current = false;
          const samples = downsample(input, context.sampleRate);
          const pcm = new Int16Array(samples.length);
          for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
          socket.send(pcm.buffer);
        };
        source.connect(processor); processor.connect(silent); silent.connect(context.destination);
        setProblem(''); setPhase('listening');
      } catch (cause) {
        const session = recognitionRef.current; recognitionRef.current = null;
        session?.processor.disconnect(); session?.silent.disconnect(); session?.stream.getTracks().forEach((track) => track.stop()); void session?.context.close();
        const failure = classifyVoiceFailure(cause);
        if (/websocket|连接/i.test(failure.detail) && failureRef.current < 2 && !mutedRef.current) {
          failureRef.current += 1; setProblem(`${failure.category}：${failure.detail}。正在尝试重连（${failureRef.current}/2）…`); setPhase('thinking');
          window.setTimeout(() => { if (!mutedRef.current && !recognitionRef.current) listen(); }, 350 * failureRef.current);
        } else { setProblem(`${failure.category}：${failure.detail}。${failure.next}`); setPhase('unavailable'); }
      }
    })();
  }, [apiBaseUrl]);

  const runIdRef = useRef(runId);
  runIdRef.current = runId;
  const onSendRef = useRef(onSend);
  onSendRef.current = onSend;

  const speak = useCallback((text: string) => {
    if (!('speechSynthesis' in window) || !text.trim()) return;
    const utterance = new SpeechSynthesisUtterance(text.trim());
    utterance.lang = 'zh-CN';
    utterance.voice = window.speechSynthesis.getVoices().find((voice) => voice.name === speechVoice) ?? null;
    pendingRef.current += 1;
    const finish = () => {
      pendingRef.current = Math.max(0, pendingRef.current - 1);
      if (pendingRef.current === 0 && doneRef.current && phaseRef.current === 'speaking') setPhase('listening');
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }, [listen, speechVoice]);

  // Stream the assistant reply into speech sentence by sentence.
  useEffect(() => {
    if (!runId || runId === staleRunRef.current) return;
    if (phaseRef.current !== 'thinking' && phaseRef.current !== 'speaking') return;
    if (trackedRunRef.current !== runId) { trackedRunRef.current = runId; spokenRef.current = 0; doneRef.current = false; }
    setSaid(reply);
    let rest = reply.slice(spokenRef.current);
    while (SENTENCE.test(rest)) {
      const boundary = rest.search(SENTENCE) + 1;
      const sentence = rest.slice(0, boundary);
      spokenRef.current += boundary;
      rest = rest.slice(boundary);
      if (sentence.trim()) { setPhase('speaking'); speak(sentence); }
    }
    if (runDone && !doneRef.current) {
      doneRef.current = true;
      if (rest.trim()) { spokenRef.current = reply.length; setPhase('speaking'); speak(rest); }
      if (pendingRef.current === 0) setPhase('listening');
    }
  }, [reply, runDone, runId, listen, speak]);

  // Start listening, run the call timer, and animate the orb from mic level.
  useEffect(() => {
    listen();
    const timer = window.setInterval(() => setSeconds((value) => value + 1), 1000);
    let frame = 0;
    let stream: MediaStream | null = null;
    let context: AudioContext | null = null;
    let analyser: AnalyserNode | null = null;
    const samples = new Uint8Array(256);
    navigator.mediaDevices?.getUserMedia({ audio: true }).then((media) => {
      stream = media;
      context = new AudioContext();
      analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaStreamSource(media).connect(analyser);
    }).catch(() => { /* orb falls back to synthetic motion */ });
    const tick = (time: number) => {
      let target = 0;
      if (phaseRef.current === 'listening' && analyser && !mutedRef.current) {
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const value of samples) sum += ((value - 128) / 128) ** 2;
        target = Math.min(1, Math.sqrt(sum / samples.length) * 6);
      } else if (phaseRef.current === 'speaking') {
        target = .35 + .3 * Math.sin(time / 140) * Math.sin(time / 330);
      } else if (phaseRef.current === 'thinking') {
        target = .15 + .1 * Math.sin(time / 400);
      }
      levelRef.current += (target - levelRef.current) * .2;
      orbRef.current?.style.setProperty('--lvl', levelRef.current.toFixed(3));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(false); };
    window.addEventListener('keydown', onKey);
    return () => {
      window.clearInterval(timer);
      cancelAnimationFrame(frame);
      window.removeEventListener('keydown', onKey);
      const recognition = recognitionRef.current;
      recognitionRef.current = null;
      if (recognition) { try { recognition.socket.send(JSON.stringify({ type: 'end' })); } catch { /* socket closed */ } recognition.processor.disconnect(); recognition.silent.disconnect(); recognition.stream.getTracks().forEach((track) => track.stop()); void recognition.context.close(); }
      window.speechSynthesis?.cancel();
      stream?.getTracks().forEach((track) => track.stop());
      void (context as AudioContext | null)?.close();
    };
  }, []);

  const toggleMute = () => {
    const next = !muted;
    setMuted(next);
    mutedRef.current = next;
    if (next) {
      const recognition = recognitionRef.current;
      recognitionRef.current = null;
      if (recognition) { try { recognition.socket.send(JSON.stringify({ type: 'end' })); } catch { /* socket closed */ } recognition.processor.disconnect(); recognition.silent.disconnect(); recognition.stream.getTracks().forEach((track) => track.stop()); void recognition.context.close(); }
      if (phaseRef.current === 'listening') setPhase('paused');
    } else if (phaseRef.current === 'paused') listen();
  };
  const interrupt = () => {
    pendingRef.current = 0;
    doneRef.current = true;
    staleRunRef.current = trackedRunRef.current ?? runIdRef.current;
    trackedRunRef.current = null;
    utteranceAcceptedRef.current = false;
    window.speechSynthesis?.cancel();
    setHeard('');
    setSaid(''); setPhase('listening');
    listen();
  };

  const state = phase === 'listening' ? '在听，你可以直接说' : phase === 'thinking' ? 'Atlas 正在想…' : phase === 'speaking' ? '正在播报，可随时插话' : phase === 'paused' ? '麦克风已静音' : '';
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

  return <section className="voice" role="dialog" aria-modal="true" aria-label="语音通话">
    <div className="vtop"><span className="live">正在和 Atlas 通话</span><b>{clock}</b><label>{modelName} · 本机语音<select aria-label="通话音色" value={speechVoice} onChange={(event) => onSpeechVoiceChange?.(event.target.value)}><option value="">系统默认</option>{speechVoices.filter((voice) => voice.lang.toLowerCase().startsWith('zh')).map((voice) => <option key={voice.name} value={voice.name}>{voice.name}</option>)}</select></label></div>
    <div className="orb" ref={orbRef}>
      <svg viewBox="0 0 400 400" aria-hidden="true">
        <defs>
          <radialGradient id="vg-core" cx="38%" cy="30%" r="80%"><stop offset="0" stopColor="#FFFFFF" stopOpacity=".95" /><stop offset=".35" stopColor="#C9D5F2" stopOpacity=".55" /><stop offset=".8" stopColor="#5E6FA8" stopOpacity=".25" /><stop offset="1" stopColor="#2A335A" stopOpacity=".4" /></radialGradient>
          <radialGradient id="vg-halo" cx="50%" cy="50%" r="50%"><stop offset=".55" stopColor="#E6BA78" stopOpacity=".35" /><stop offset="1" stopColor="#E6BA78" stopOpacity="0" /></radialGradient>
          <linearGradient id="vg-ring" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#F3D29D" /><stop offset=".5" stopColor="#C08A45" stopOpacity=".6" /><stop offset="1" stopColor="#F3D29D" /></linearGradient>
        </defs>
        <circle className="halo" cx="200" cy="200" r="200" fill="url(#vg-halo)" />
        <g className="ring r1"><ellipse cx="200" cy="200" rx="178" ry="58" fill="none" stroke="url(#vg-ring)" strokeWidth="2" transform="rotate(-22 200 200)" /></g>
        <g className="ring r2"><ellipse cx="200" cy="200" rx="58" ry="178" fill="none" stroke="url(#vg-ring)" strokeWidth="1.2" opacity=".7" transform="rotate(-22 200 200)" /></g>
        <g className="ring r3"><ellipse cx="200" cy="200" rx="160" ry="160" fill="none" stroke="#F3D29D" strokeWidth=".8" strokeDasharray="2 7" opacity=".5" /></g>
        <g className="core"><circle cx="200" cy="200" r="112" fill="url(#vg-core)" stroke="rgba(255,255,255,.35)" strokeWidth="1" /><ellipse cx="160" cy="150" rx="34" ry="22" fill="#fff" opacity=".55" transform="rotate(-30 160 150)" /></g>
      </svg>
    </div>
    <div className="captions" aria-live="polite">
      {captions && heard && <p className="you">“{heard}”</p>}
      {captions && said && phase !== 'listening' && <p className="atlas">{said}</p>}
      {state && <p className="state">{state}</p>}
      {phase === 'unavailable' && <div role="alert" className="state"><b>{classifyVoiceFailure(problem).category}</b><p>{problem}</p><div className="flex justify-center gap-2"><button onClick={() => { failureRef.current = 0; setPhase('listening'); listen(); }}><RotateCcw size={13} className="mr-1 inline" />重试</button><button onClick={() => onClose(true)}><MessageSquareText size={13} className="mr-1 inline" />转为文字</button></div></div>}
    </div>
    <div className="vctl">
      <div className="vlabel"><button aria-pressed={muted} aria-label="静音" onClick={toggleMute}><MicOff size={20} /></button>静音</div>
      <div className="vlabel"><button aria-label="打断 Atlas" disabled={phase !== 'speaking'} onClick={interrupt}><Hand size={20} /></button>打断</div>
      <div className="vlabel"><button className="end" aria-label="挂断" onClick={() => onClose(false)}><PhoneOff size={22} /></button>挂断</div>
      <div className="vlabel"><button aria-pressed={captions} aria-label="显示字幕" onClick={() => setCaptions((value) => !value)}><Captions size={20} /></button>字幕</div>
      <div className="vlabel"><button aria-label="转成文字对话" onClick={() => onClose(true)}><MessageSquareText size={20} /></button>转文字</div>
    </div>
  </section>;
}
