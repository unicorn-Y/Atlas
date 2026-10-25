/** Parse explicit line-start memory markers while leaving the original message untouched. */
export function extractMemoryMarkers(message: string): string[] {
  const candidates: string[] = [];
  let current: string[] = [];
  let inFence = false;
  const commit = () => {
    const text = current.join('\n').trim();
    if (text) candidates.push(text);
    current = [];
  };
  for (const line of message.split(/\r?\n/)) {
    if (/^\s*(```|~~~)/.test(line)) {
      commit();
      inFence = !inFence;
      continue;
    }
    if (inFence) continue;
    const marker = /^\s*#(?!##)(?:记住(?:[:：]\s*|\s+)|\s+)(.*)$/.exec(line);
    if (marker) {
      commit();
      if (marker[1].trim()) current = [marker[1].trim()];
      continue;
    }
    if (/^\s*\\#/.test(line)) {
      commit();
      continue;
    }
    if (current.length && line.trim()) current.push(line.trim());
    else commit();
  }
  commit();
  return candidates;
}
