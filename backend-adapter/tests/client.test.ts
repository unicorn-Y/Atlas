import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendAdapter } from '../src/client';

class MockWebSocket extends EventTarget {
  static instances: MockWebSocket[] = [];
  readyState = 0;
  sent: string[] = [];

  constructor(readonly url: string) {
    super();
    MockWebSocket.instances.push(this);
  }

  send(data: string) { this.sent.push(data); }
  open() { this.readyState = 1; this.dispatchEvent(new Event('open')); }
  receive(data: unknown) { this.dispatchEvent(Object.assign(new Event('message'), { data: JSON.stringify(data) })); }
  disconnect() { this.readyState = 3; this.dispatchEvent(new Event('close')); }
  close() { this.disconnect(); }
}

const runtimeEvent = (sequence: number, event: string) => ({
  type: 'agent_event', event_id: `event-${sequence}`, run_id: 'run-1', sequence,
  timestamp: new Date(0).toISOString(), event, data: {},
});

const flushAsync = () => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
  MockWebSocket.instances = [];
});

describe('BackendAdapter availability and recovery', () => {
  it('can recover from an unavailable backend when initialized again', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });

    await expect(adapter.initialize()).resolves.toBe('mock');
    expect(adapter.availabilityError).toBe('offline');
    await expect(adapter.initialize()).resolves.toBe('backend');
    expect(adapter.availabilityError).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('marks a server failure unavailable and clears it after a health check recovers', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'temporarily unavailable' }) } as Response)
      .mockResolvedValueOnce({ ok: true } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.getModels()).rejects.toThrow('temporarily unavailable');
    expect(adapter.mode).toBe('mock');
    expect(adapter.availabilityError).toBe('temporarily unavailable');
    await expect(adapter.initialize()).resolves.toBe('backend');
    expect(adapter.availabilityError).toBeNull();
  });

  it('accepts successful empty responses for void backend operations', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true } as Response)
      .mockResolvedValueOnce({ ok: true, status: 204, json: async () => { throw new SyntaxError('empty response'); } } as Response);
    vi.stubGlobal('fetch', fetchMock);
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();

    await expect(adapter.deleteFact('temporary')).resolves.toBeUndefined();
  });

  it('resumes the same run after disconnect and ignores replayed events', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('window', { setTimeout: (callback: TimerHandler, delay?: number) => setTimeout(callback, delay) });
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', {
      values: new Map<string, string>(),
      getItem(key: string) { return this.values.get(key) ?? null; },
      setItem(key: string, value: string) { this.values.set(key, value); },
      removeItem(key: string) { this.values.delete(key); },
    });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const events: number[] = [];
    const running = adapter.startRun({ type: 'run.start', run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' }, (event) => events.push(event.sequence));

    await vi.advanceTimersByTimeAsync(0);
    const first = MockWebSocket.instances[0];
    first.open();
    expect(JSON.parse(first.sent[0]).type).toBe('run.start');
    first.receive(runtimeEvent(1, 'run.started'));
    first.disconnect();
    await vi.advanceTimersByTimeAsync(1_000);

    const resumed = MockWebSocket.instances[1];
    expect(resumed).toBeDefined();
    resumed.open();
    expect(JSON.parse(resumed.sent[0])).toEqual({ type: 'resume', run_id: 'run-1', after_sequence: 1 });
    resumed.receive(runtimeEvent(1, 'run.started'));
    resumed.receive(runtimeEvent(2, 'message.completed'));
    resumed.receive(runtimeEvent(3, 'run.completed'));
    await running;

    expect(events).toEqual([1, 2, 3]);
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it('rejects a second start for a run that is already connecting', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const request = { type: 'run.start' as const, run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' };
    const running = adapter.startRun(request, () => undefined);

    await flushAsync();
    await expect(Promise.race([
      adapter.startRun(request, () => undefined),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error('duplicate start did not reject')), 50)),
    ])).rejects.toThrow('Run run-1 is already active');
    expect(MockWebSocket.instances).toHaveLength(1);
    MockWebSocket.instances[0].open();
    MockWebSocket.instances[0].receive(runtimeEvent(1, 'run.completed'));
    await running;
  });

  it('surfaces a websocket connection failure and releases the run reservation', async () => {
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      return url.endsWith('/api/health')
        ? { ok: true } as Response
        : { ok: true, json: async () => ({ version: '1.2' }) } as Response;
    }));
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.stubGlobal('localStorage', { getItem: () => null, setItem: () => undefined, removeItem: () => undefined });
    const adapter = new BackendAdapter({ baseUrl: 'http://localhost:8765' });
    await adapter.initialize();
    const request = { type: 'run.start' as const, run_id: 'run-1', content: 'hello', conversation_id: 'conv-1' };
    const failed = adapter.startRun(request, () => undefined);
    await flushAsync();
    MockWebSocket.instances[0].dispatchEvent(new Event('error'));
    await expect(failed).rejects.toThrow('WebSocket connection failed');

    await expect(adapter.initialize()).resolves.toBe('backend');
    const retried = adapter.startRun(request, () => undefined);
    await flushAsync();
    MockWebSocket.instances[1].open();
    MockWebSocket.instances[1].receive(runtimeEvent(1, 'run.completed'));
    await retried;
    expect(MockWebSocket.instances).toHaveLength(2);
  });
});
