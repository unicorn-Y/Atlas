import { afterEach, describe, expect, it, vi } from 'vitest';
import { cancelRoutedSpeech, speakRouted } from './speechPlayback';

class FakeAudio {
  static latest: FakeAudio | null = null;
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  setSinkId = vi.fn().mockResolvedValue(undefined);
  pause = vi.fn();
  play = vi.fn(async () => { queueMicrotask(() => this.onended?.()); });
  src = '';
  constructor(public readonly source: string) { FakeAudio.latest = this; }
}

describe('speakRouted', () => {
  afterEach(() => { cancelRoutedSpeech(); vi.unstubAllGlobals(); });

  it('synthesizes desktop speech and routes playback to the saved output', async () => {
    const synthesizeSpeech = vi.fn().mockResolvedValue('d2F0');
    vi.stubGlobal('localStorage', { getItem: () => 'speaker-2', removeItem: vi.fn() });
    vi.stubGlobal('window', Object.assign(new EventTarget(), { atlasDesktop: { synthesizeSpeech }, speechSynthesis: { cancel: vi.fn() } }));
    vi.stubGlobal('Audio', FakeAudio);
    await speakRouted('测试播报', { voice: 'voice', rate: 1.2 });
    expect(synthesizeSpeech).toHaveBeenCalledWith('测试播报', 'voice', 1.2);
    expect(FakeAudio.latest?.setSinkId).toHaveBeenCalledWith('speaker-2');
    expect(FakeAudio.latest?.play).toHaveBeenCalledOnce();
  });
});
