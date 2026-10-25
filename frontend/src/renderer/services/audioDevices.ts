export async function getSelectedInputStream(constraints: MediaTrackConstraints = {}): Promise<{ stream: MediaStream; usedFallback: boolean }> {
  const selected = localStorage.getItem('atlas.audio.input-device') || '';
  const audio = (deviceId?: string): MediaStreamConstraints => ({ audio: { ...constraints, ...(deviceId ? { deviceId: { exact: deviceId } } : {}) } });
  try { return { stream: await navigator.mediaDevices.getUserMedia(audio(selected)), usedFallback: false }; }
  catch (cause) {
    if (!selected) throw cause;
    const stream = await navigator.mediaDevices.getUserMedia(audio());
    localStorage.removeItem('atlas.audio.input-device');
    return { stream, usedFallback: true };
  }
}
