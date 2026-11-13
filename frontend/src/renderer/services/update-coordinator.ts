export type UpdateJournalEntry = {
  at: string;
  event: 'check.started' | 'check.completed' | 'check.failed';
  channel: string;
  current?: string;
  latest?: string;
  error?: string;
};

type CoordinatorOptions<T> = {
  check: () => Promise<T>;
  journal: (entry: UpdateJournalEntry) => void;
  onResult?: (result: T) => void;
  channel?: string | (() => string);
  intervalMs?: number;
  initialDelayMs?: number;
  baseBackoffMs?: number;
  maxBackoffMs?: number;
  random?: () => number;
  now?: () => Date;
};

export function createUpdateCoordinator<T>(options: CoordinatorOptions<T>) {
  const intervalMs = options.intervalMs ?? 5 * 60_000;
  const baseBackoffMs = options.baseBackoffMs ?? 10_000;
  const maxBackoffMs = options.maxBackoffMs ?? 30 * 60_000;
  const random = options.random ?? Math.random;
  const now = options.now ?? (() => new Date());
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = true;
  let running = false;
  let failures = 0;

  const record = (event: UpdateJournalEntry['event'], fields: Partial<UpdateJournalEntry> = {}) => {
    const channel = typeof options.channel === 'function' ? options.channel() : options.channel;
    options.journal({ at: now().toISOString(), event, channel: channel ?? 'release', ...fields });
  };
  const schedule = (delay: number) => {
    if (stopped) return;
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => { timer = undefined; void run(); }, delay);
  };
  const run = async () => {
    if (stopped || running) return;
    running = true;
    record('check.started');
    try {
      const result = await options.check();
      failures = 0;
      const status = result as { current?: string; latest?: string };
      record('check.completed', { current: status.current, latest: status.latest });
      options.onResult?.(result);
      schedule(intervalMs);
    } catch (error) {
      failures += 1;
      const cap = Math.min(maxBackoffMs, baseBackoffMs * 2 ** Math.min(failures - 1, 30));
      const jittered = Math.round(cap * (0.8 + Math.max(0, Math.min(1, random())) * 0.4));
      record('check.failed', { error: error instanceof Error ? error.message : String(error) });
      schedule(Math.min(maxBackoffMs, jittered));
    } finally {
      running = false;
    }
  };

  return {
    start() {
      if (!stopped) return;
      stopped = false;
      schedule(options.initialDelayMs ?? 0);
    },
    checkNow() { if (!stopped && !running) schedule(0); },
    stop() {
      stopped = true;
      if (timer !== undefined) clearTimeout(timer);
      timer = undefined;
    },
  };
}

export function appendUpdateJournal(entry: UpdateJournalEntry, storage: Pick<Storage, 'getItem' | 'setItem'>, limit = 200): void {
  try {
    const current = JSON.parse(storage.getItem('atlas.update.journal') ?? '[]') as unknown;
    const entries = Array.isArray(current) ? current.filter((item): item is UpdateJournalEntry => Boolean(item && typeof item === 'object' && 'event' in item)) : [];
    storage.setItem('atlas.update.journal', JSON.stringify([...entries, entry].slice(-limit)));
  } catch { /* storage can be unavailable or contain invalid prior data */ }
}
