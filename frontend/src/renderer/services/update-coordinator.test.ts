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

  it('checks on the configured interval after success and cancels scheduled checks on stop', async () => {
    vi.useFakeTimers();
    try {
      const check = vi.fn().mockResolvedValue({ current: '1.0.0', latest: '1.1.0' });
      const journal = vi.fn();
      const onResult = vi.fn();
      const coordinator = createUpdateCoordinator({ check, journal, onResult, initialDelayMs: 100, intervalMs: 1000 });
      coordinator.start();
      coordinator.start();
      await vi.advanceTimersByTimeAsync(99);
      expect(check).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(1);
      expect(check).toHaveBeenCalledOnce();
      expect(onResult).toHaveBeenCalledWith({ current: '1.0.0', latest: '1.1.0' });
      expect(journal).toHaveBeenLastCalledWith(expect.objectContaining({ current: '1.0.0', latest: '1.1.0' }));
      await vi.advanceTimersByTimeAsync(1000);
      expect(check).toHaveBeenCalledTimes(2);
      coordinator.stop();
      await vi.advanceTimersByTimeAsync(10_000);
      expect(check).toHaveBeenCalledTimes(2);
    } finally { vi.useRealTimers(); }
  });

  it('never starts overlapping checks when focus requests another check', async () => {
    vi.useFakeTimers();
    try {
      let complete!: (value: { available: boolean }) => void;
      const check = vi.fn(() => new Promise<{ available: boolean }>((resolve) => { complete = resolve; }));
      const coordinator = createUpdateCoordinator({ check, journal: vi.fn() });
      coordinator.start();
      await vi.advanceTimersByTimeAsync(0);
      coordinator.checkNow();
      await vi.advanceTimersByTimeAsync(0);
      expect(check).toHaveBeenCalledOnce();
      complete({ available: false });
      await Promise.resolve();
      coordinator.stop();
    } finally { vi.useRealTimers(); }
  });
});
