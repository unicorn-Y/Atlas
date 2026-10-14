import { describe, expect, it } from 'vitest';
import { toReminders } from './RemindersView';

describe('toReminders', () => {
  it('keeps only chat reminders, pending first', () => {
    const list = toReminders([
      { id: 'job', name: 'nightly digest', enabled: true },
      { id: 'a', name: '提醒：喝水', enabled: false, trigger: { at: '2026-10-10T12:00:00+08:00' } },
      { id: 'b', name: '提醒：交周报', enabled: true, trigger: { at: '2026-10-11T09:00:00+08:00' } },
      { id: 'c', name: '提醒：开会', enabled: true, trigger: { at: '2026-10-09T09:00:00+08:00' }, state: { last_run_at: 'x' } },
    ]);
    expect(list.map((r) => [r.id, r.text, r.state])).toEqual([
      ['b', '交周报', 'pending'], ['a', '喝水', 'cancelled'], ['c', '开会', 'done'],
    ]);
  });
});
