import { describe, expect, it, vi } from 'vitest';
import { appendUpdateJournal, createUpdateCoordinator } from './update-coordinator';

describe('update coordinator', () => {
  it('journals checks and retries failures with bounded exponential backoff and jitter', async () => {
    vi.useFakeTimers();
    const check = vi.fn().mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ available: false });
    const journal = vi.fn();
    const coordinator = createUpdateCoordinator({ check, journal, random: () => 0.25, intervalMs: 60_000, baseBackoffMs: 1_000, maxBackoffMs: 8_000 });

    coordinator.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(check).toHaveBeenCalledTimes(1);
    expect(journal).toHaveBeenLastCalledWith(expect.objectContaining({ event: 'check.failed', error: 'offline' }));

    await vi.advanceTimersByTimeAsync(899);
    expect(check).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(check).toHaveBeenCalledTimes(2);
    expect(journal).toHaveBeenLastCalledWith(expect.objectContaining({ event: 'check.completed' }));
    coordinator.stop();
    vi.useRealTimers();
  });

  it('caps its persisted journal to the newest entries', () => {
    const values = new Map<string, string>();
    const storage = { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value) };
    appendUpdateJournal({ at: '1', event: 'check.started', channel: 'release' }, storage, 2);
    appendUpdateJournal({ at: '2', event: 'check.completed', channel: 'release' }, storage, 2);
    appendUpdateJournal({ at: '3', event: 'check.failed', channel: 'release', error: 'offline' }, storage, 2);
    expect(JSON.parse(values.get('atlas.update.journal') ?? '[]').map((entry: { at: string }) => entry.at)).toEqual(['2', '3']);
  });
});
