import { describe, expect, it } from 'vitest';
import { splitFacts, type UserFact } from './FactsView';
import { toItems } from './LibraryView';
import { toReminders } from './RemindersView';

const fact = (over: Partial<UserFact>): UserFact => ({
  id: 'f', factKey: 'k', value: 'v', text: 't', status: 'active', evidenceQuote: 'q',
  createdAt: 0, updatedAt: 0, forgetAfter: null, ...over,
});

describe('splitFacts', () => {
  it('keeps active, unexpired facts current and explains the rest', () => {
    const now = 1_000;
    const { current, history } = splitFacts([
      fact({ id: 'live' }),
      fact({ id: 'temp', forgetAfter: 2_000 }),
      fact({ id: 'expired', forgetAfter: 500 }),
      fact({ id: 'old', status: 'superseded' }),
      fact({ id: 'gone', status: 'retracted' }),
    ], now);
    expect(current.map((f) => f.id)).toEqual(['live', 'temp']);
    expect(history.map((f) => [f.id, f.why.endsWith('已过期') ? '过期' : f.why])).toEqual([
      ['expired', '过期'], ['old', '已被新说法替代'], ['gone', '已撤销'],
    ]);
  });
});

describe('toItems', () => {
  it('normalises the three MemOS list shapes', () => {
    expect(toItems('skills', { skills: [{ id: 's1', name: '部署', invocationGuide: 'npm run deploy', status: 'active', updatedAt: 0 }] })[0])
      .toMatchObject({ id: 's1', title: '部署', detail: 'npm run deploy', status: 'active' });
    expect(toItems('policies', { policies: [{ id: 'p1', title: '先跑测试', trigger: '改代码后', status: 'candidate' }] })[0])
      .toMatchObject({ title: '先跑测试', detail: '改代码后' });
    expect(toItems('world_model', { worldModels: [{ id: 'w1', title: 'Atlas 仓库', body: 'D:\Atlas' }] })[0])
      .toMatchObject({ title: 'Atlas 仓库', detail: 'D:\Atlas' });
    expect(toItems('skills', {})).toEqual([]);
  });
});

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
