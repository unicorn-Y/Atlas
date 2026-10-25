import { afterEach, describe, expect, it, vi } from 'vitest';
import { getSelectedInputStream } from './audioDevices';

describe('getSelectedInputStream', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('uses the saved device when it is available', async () => {
    const stream = {} as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.stubGlobal('localStorage', { getItem: () => 'mic-1', removeItem: vi.fn() });
    await expect(getSelectedInputStream({ echoCancellation: true })).resolves.toEqual({ stream, usedFallback: false });
    expect(getUserMedia).toHaveBeenCalledWith({ audio: { echoCancellation: true, deviceId: { exact: 'mic-1' } } });
  });

  it('falls back to the system default and clears a missing saved device', async () => {
    const stream = {} as MediaStream;
    const getUserMedia = vi.fn().mockRejectedValueOnce(new Error('device missing')).mockResolvedValueOnce(stream);
    const removeItem = vi.fn();
    vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
    vi.stubGlobal('localStorage', { getItem: () => 'mic-1', removeItem });
    await expect(getSelectedInputStream({ channelCount: 1 })).resolves.toEqual({ stream, usedFallback: true });
    expect(getUserMedia).toHaveBeenLastCalledWith({ audio: { channelCount: 1 } });
    expect(removeItem).toHaveBeenCalledWith('atlas.audio.input-device');
  });
});
