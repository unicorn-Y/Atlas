import { expect, it } from 'vitest';
import { normalizeRuntimeEvent } from './runtimeEvents';
import { buildTimeline } from '../components/timeline';

it('renders output matches and heartbeat notifications delivered by the backend', () => {
  for (const reason of ['watch', 'heartbeat']) {
    const event = normalizeRuntimeEvent({ event: 'process.notification', event_id: reason,
      run_id: 'run', sequence: 1, timestamp: '2026-10-02T00:00:00Z',
      data: { reason, text: 'READY' } } as Parameters<typeof normalizeRuntimeEvent>[0]);
    expect(event?.type).toBe('process.notification');
    const timeline = buildTimeline([event!]);
    expect(timeline.some(item => item.kind === 'notice' && item.text.includes(reason === 'watch' ? 'READY' : '仍在运行'))).toBe(true);
  }
});
