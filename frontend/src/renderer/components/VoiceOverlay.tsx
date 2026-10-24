import { useCallback, useEffect, useRef, useState } from 'react';
import { Captions, MessageSquareText, MicOff, PhoneOff, Hand } from 'lucide-react';
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
}

const SENTENCE = /[。！？.!?；;\n]/;
export default function VoiceOverlay({ apiBaseUrl, onClose, onSend, runId, reply, runDone, modelName }: VoiceOverlayProps) {
  const [phase, setPhase] = useState<Phase>('listening');
  const [heard, setHeard] = useState('');
  const [said, setSaid] = useState('');
  const [captions, setCaptions] = useState(true);
  const [muted, setMuted] = useState(false);
  const [problem, setProblem] = useState('');
  const [seconds, setSeconds] = useState(0);
  const orbRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<{ socket: WebSocket; stream: MediaStream; context: AudioContext; processor: ScriptProcessorNode } | null>(null);
  const levelRef = useRef(0);
  const phaseRef = useRef<Phase>('listening');
  const mutedRef = useRef(false);
  const staleRunRef = useRef<string | null>(runId);
  const trackedRunRef = useRef<string | null>(null);
  const spokenRef = useRef(0);
  const pendingRef = useRef(0);
  const doneRef = useRef(false);
  phaseRef.current = phase;
  mutedRef.current = muted;

  const listen = useCallback(() => {
    if (mutedRef.current) { setPhase('paused'); return; }
    void (async () => {
      try {
        const status = await api<{ ready: boolean; message?: string }>(apiBaseUrl, '/api/asr/status');
        if (!status.ready) { setProblem(status.message || '请先准备本地语音识别模型。'); setPhase('unavailable'); return; }
        const inputDevice = localStorage.getItem('atlas.audio.input-device') || '';
        const stream = await navigator.mediaDevices.getUserMedia({ audio: { ...(inputDevice ? { deviceId: { exact: inputDevice } } : {}), channelCount: 1, echoCancellation: true, noiseSuppression: true } });
        const context = new AudioContext();
        const source = context.createMediaStreamSource(stream);
        const processor = context.createScriptProcessor(4096, 1, 1);
        const socketUrl = new URL('/ws/asr', apiBaseUrl); socketUrl.protocol = socketUrl.protocol === 'https:' ? 'wss:' : 'ws:';
        const socket = new WebSocket(socketUrl);
        const session = { socket, stream, context, processor };
        recognitionRef.current = session;
        let submitted = false;
        socket.onmessage = (event) => {
          try {
            const message = JSON.parse(String(event.data)) as { type?: string; text?: string; detail?: string };
            if (message.type === 'partial') setHeard(message.text || '');
            if (message.type === 'final' && message.text?.trim() && !submitted) {
              submitted = true; setHeard(message.text.trim()); recognitionRef.current = null;
              try { socket.send(JSON.stringify({ type: 'end' })); } catch { /* closed */ }
              processor.disconnect(); stream.getTracks().forEach((track) => track.stop()); void context.close();
              staleRunRef.current = trackedRunRef.current ?? runIdRef.current; setSaid(''); setPhase('thinking'); onSendRef.current(message.text.trim());
            }
            if (message.type === 'error') { setProblem(message.detail || '本地语音识别失败。'); setPhase('unavailable'); }
          } catch { /* malformed local ASR response */ }
        };
        socket.onerror = () => { setProblem('本地语音识别连接失败。'); setPhase('unavailable'); };
        await new Promise<void>((resolve, reject) => { socket.addEventListener('open', () => resolve(), { once: true }); socket.addEventListener('error', () => reject(new Error('本地语音识别连接失败')), { once: true }); });
        const downsample = (samples: Float32Array, from: number) => {
          if (from <= 16000) return samples;
          const ratio = from / 16000; const output = new Float32Array(Math.floor(samples.length / ratio));
          for (let i = 0; i < output.length; i++) output[i] = samples[Math.floor(i * ratio)];
          return output;
        };
        processor.onaudioprocess = (event) => {
          if (socket.readyState !== WebSocket.OPEN) return;
          const samples = downsample(event.inputBuffer.getChannelData(0), context.sampleRate);
          const pcm = new Int16Array(samples.length);
          for (let i = 0; i < samples.length; i++) pcm[i] = Math.max(-1, Math.min(1, samples[i])) * 0x7fff;
          socket.send(pcm.buffer);
        };
        source.connect(processor); processor.connect(context.destination);
        setProblem(''); setPhase('listening');
      } catch (cause) {
        const session = recognitionRef.current; recognitionRef.current = null;
        session?.stream.getTracks().forEach((track) => track.stop()); void session?.context.close();
        setProblem(cause instanceof Error ? cause.message : '本地语音识别启动失败。'); setPhase('unavailable');
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
    pendingRef.current += 1;
    const finish = () => {
      pendingRef.current = Math.max(0, pendingRef.current - 1);
      if (pendingRef.current === 0 && doneRef.current && phaseRef.current === 'speaking') listen();
    };
    utterance.onend = finish;
    utterance.onerror = finish;
    window.speechSynthesis.speak(utterance);
  }, [listen]);

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
      if (pendingRef.current === 0) listen();
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
      if (recognition) { try { recognition.socket.send(JSON.stringify({ type: 'end' })); } catch { /* socket closed */ } recognition.processor.disconnect(); recognition.stream.getTracks().forEach((track) => track.stop()); void recognition.context.close(); }
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
      if (recognition) { try { recognition.socket.send(JSON.stringify({ type: 'end' })); } catch { /* socket closed */ } recognition.processor.disconnect(); recognition.stream.getTracks().forEach((track) => track.stop()); void recognition.context.close(); }
      if (phaseRef.current === 'listening') setPhase('paused');
    } else if (phaseRef.current === 'paused') listen();
  };
  const interrupt = () => {
    pendingRef.current = 0;
    doneRef.current = true;
    staleRunRef.current = trackedRunRef.current ?? runIdRef.current;
    window.speechSynthesis?.cancel();
    setHeard('');
    listen();
  };

  const state = phase === 'listening' ? '在听，你可以直接说' : phase === 'thinking' ? 'Atlas 正在想…' : phase === 'speaking' ? '' : phase === 'paused' ? '麦克风已静音' : problem;
  const clock = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;

  return <section className="voice" role="dialog" aria-modal="true" aria-label="语音通话">
    <div className="vtop"><span className="live">正在和 Atlas 通话</span><b>{clock}</b><span>{modelName} · 本机语音</span></div>
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
