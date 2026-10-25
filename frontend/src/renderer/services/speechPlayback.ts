type SpeechOptions = { voice?: string; rate?: number; lang?: string; onError?: (message: string) => void };

let generation = 0;
let queue = Promise.resolve();
let activeAudio: HTMLAudioElement | null = null;
let finishActive: (() => void) | null = null;

function fallbackSpeech(text: string, options: SpeechOptions, run: number): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!('speechSynthesis' in window)) { reject(new Error('此环境没有可用的语音合成器。')); return; }
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = options.lang ?? 'zh-CN';
    utterance.rate = options.rate ?? 1;
    utterance.voice = window.speechSynthesis.getVoices().find((voice) => voice.name === options.voice) ?? null;
    utterance.onend = () => resolve();
    utterance.onerror = (event) => reject(new Error(event.error || '语音播放失败'));
    if (run === generation) window.speechSynthesis.speak(utterance);
    else resolve();
  });
}

async function playRouted(text: string, options: SpeechOptions, run: number): Promise<void> {
  const output = localStorage.getItem('atlas.audio.output-device') || '';
  if (!output) return fallbackSpeech(text, options, run);
  const synthesize = window.atlasDesktop?.synthesizeSpeech;
  if (!synthesize) throw new Error('所选扬声器需要桌面语音路由支持；请切换为系统默认输出。');
  const encoded = await synthesize(text, options.voice ?? '', options.rate ?? 1);
  if (run !== generation) return;
  const audio = new Audio(`data:audio/wav;base64,${encoded}`);
  const routed = audio as HTMLAudioElement & { setSinkId?: (id: string) => Promise<void> };
  if (!routed.setSinkId) throw new Error('当前桌面 Chromium 不支持指定扬声器；请切换为系统默认输出。');
  activeAudio = audio;
  try {
    await routed.setSinkId(output);
    if (run !== generation) return;
    await new Promise<void>((resolve, reject) => {
      const finish = () => { finishActive = null; resolve(); };
      finishActive = finish;
      audio.onended = finish;
      audio.onerror = () => { finishActive = null; reject(new Error('所选扬声器播放失败。')); };
      void audio.play().catch(reject);
    });
  } catch (cause) {
    const message = cause instanceof Error ? cause.message : String(cause);
    localStorage.removeItem('atlas.audio.output-device');
    window.dispatchEvent(new Event('atlas-audio-output-fallback'));
    options.onError?.(`所选扬声器不可用，已回落到系统默认输出：${message}`);
    if (run === generation) await fallbackSpeech(text, options, run);
  } finally {
    if (activeAudio === audio) activeAudio = null;
    audio.pause(); audio.src = '';
  }
}

export function speakRouted(text: string, options: SpeechOptions = {}): Promise<void> {
  const clean = text.trim();
  if (!clean) return Promise.resolve();
  const run = generation;
  const item = queue.then(() => run === generation ? playRouted(clean, options, run) : undefined);
  queue = item.catch((cause: unknown) => {
    const message = cause instanceof Error ? cause.message : String(cause);
    options.onError?.(message);
  });
  return item;
}

export function cancelRoutedSpeech(): void {
  generation += 1;
  queue = Promise.resolve();
  window.speechSynthesis?.cancel();
  if (activeAudio) { activeAudio.pause(); activeAudio.src = ''; activeAudio = null; }
  finishActive?.(); finishActive = null;
}
