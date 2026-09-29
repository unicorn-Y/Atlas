import { useCallback, useEffect, useRef, useState } from 'react';
import { Captions, MessageSquareText, MicOff, PhoneOff, Hand } from 'lucide-react';

export type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous?: boolean;
  onresult: ((event: { resultIndex: number; results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }> }) => void) | null;
  onerror: ((event?: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort?: () => void;
};

export function getSpeechRecognition(): (new () => SpeechRecognitionLike) | undefined {
  const speechWindow = window as typeof window & { SpeechRecognition?: new () => SpeechRecognitionLike; webkitSpeechRecognition?: new () => SpeechRecognitionLike };
  return speechWindow.SpeechRecognition ?? speechWindow.webkitSpeechRecognition;
}

type Phase = 'listening' | 'thinking' | 'speaking' | 'paused' | 'unavailable';

interface VoiceOverlayProps {
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
const ERROR_TEXT: Record<string, string> = {
  'not-allowed': '没有麦克风权限。请在系统设置里允许 Atlas 使用麦克风。',
  'service-not-allowed': '没有麦克风权限。请在系统设置里允许 Atlas 使用麦克风。',
  network: '语音识别服务连不上。当前设备的语音识别需要联网。',
  'audio-capture': '没有检测到麦克风。',
};

export default function VoiceOverlay({ onClose, onSend, runId, reply, runDone, modelName }: VoiceOverlayProps) {
  const [phase, setPhase] = useState<Phase>('listening');
  const [heard, setHeard] = useState('');
  const [said, setSaid] = useState('');
  const [captions, setCaptions] = useState(true);
  const [muted, setMuted] = useState(false);
  const [problem, setProblem] = useState('');
  const [seconds, setSeconds] = useState(0);
  const orbRef = useRef<HTMLDivElement>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
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
    const Constructor = getSpeechRecognition();
    if (!Constructor) { setProblem('此设备不支持语音识别。可以转成文字对话继续。'); setPhase('unavailable'); return; }
    recognitionRef.current?.abort?.();
    const recognition = new Constructor();
    recognition.lang = 'zh-CN';
    recognition.interimResults = true;
    recognition.continuous = false;
    let finalText = '';
    recognition.onresult = (event) => {
      const text = Array.from(event.results).map((result) => result[0].transcript).join('');
      setHeard(text);
      finalText = text;
    };
    recognition.onerror = (event) => {
      const code = event?.error ?? '';
      if (code === 'no-speech' || code === 'aborted') return;
      setProblem(ERROR_TEXT[code] ?? `语音识别出错（${code || '未知原因'}）。`);
      setPhase('unavailable');
    };
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return;
      recognitionRef.current = null;
      if (phaseRef.current !== 'listening') return;
      const text = finalText.trim();
      if (text) {
        staleRunRef.current = trackedRunRef.current ?? runIdRef.current;
        setSaid('');
        setPhase('thinking');
        onSendRef.current(text);
      } else if (!mutedRef.current) {
        window.setTimeout(() => { if (phaseRef.current === 'listening' && !recognitionRef.current) listen(); }, 250);
      }
    };
    recognitionRef.current = recognition;
    setProblem('');
    setPhase('listening');
    try { recognition.start(); } catch { /* already started */ }
  }, []);

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
      recognition?.abort?.();
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
      recognition?.abort?.();
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
