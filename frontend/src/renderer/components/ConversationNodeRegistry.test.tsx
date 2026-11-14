import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { AgentEvent } from '../../types/runtime';
import {
  registerConversationNode,
  TimelineRow,
  type TimelineRowContext,
} from './ConversationActivity';
import { buildTimeline } from './timeline';
import type { TimelineItem } from './timeline';

describe('ConversationNode registry', () => {
  it('renders built-in timeline kinds through the keyed registry', () => {
    const item: TimelineItem = { kind: 'user', id: 'user-1', content: 'hello registry', timestamp: '2026-11-14T10:00:00Z' };
    const context = { events: [], store: {}, username: 'User', setTab: () => undefined, busy: false } as unknown as TimelineRowContext;
    expect(renderToStaticMarkup(<TimelineRow item={item} context={context} firstInTurn={false} last={false} />))
      .toContain('hello registry');
    expect(() => registerConversationNode({ kind: 'user', renderer: () => null })).toThrow('already registered');
  });

  it('renders a registered extension node and removes it with its disposer', () => {
    const dispose = registerConversationNode({
      kind: 'custom-card',
      renderer: ({ item }) => <strong>{item.kind === 'extension' ? String(item.data.label ?? '') : ''}</strong>,
    });
    const item: TimelineItem = {
      kind: 'extension', id: 'ext-1', nodeType: 'custom-card', data: { label: 'extension rendered' },
    };
    const context = { events: [], store: {}, username: 'User', setTab: () => undefined, busy: false } as unknown as TimelineRowContext;

    expect(renderToStaticMarkup(<TimelineRow item={item} context={context} firstInTurn={false} last={false} />))
      .toContain('extension rendered');
    dispose();
    expect(renderToStaticMarkup(<TimelineRow item={item} context={context} firstInTurn={false} last={false} />))
      .toBe('');
  });

  // X27: the timeline itself must be able to produce kind:'extension' nodes, otherwise the
  // registry above is unreachable from the event stream no matter what an extension registers.
  it('turns an event claimed by a registered definition into an extension timeline node and renders it', () => {
    const claimed: AgentEvent = {
      id: 'safety-1', runId: 'r1', sequence: 1, type: 'safety.reviewed',
      timestamp: '2026-11-14T10:00:00Z', data: { verdict: 'allow', reason: 'no secrets' },
    };
    // Unclaimed, the built-in timeline has no case for safety.reviewed and drops it.
    expect(buildTimeline([claimed])).toEqual([]);

    const dispose = registerConversationNode({
      kind: 'safety-card',
      renderer: ({ item }) => <strong data-node-type={item.kind === 'extension' ? item.nodeType : undefined}>
        {item.kind === 'extension' ? String(item.data.verdict ?? '') : ''}
      </strong>,
      match: (event) => event.type === 'safety.reviewed',
    });
    try {
      const items = buildTimeline([claimed]);
      expect(items).toHaveLength(1);
      expect(items[0]).toMatchObject({ kind: 'extension', id: 'safety-1', nodeType: 'safety-card', data: { verdict: 'allow', reason: 'no secrets' } });

      const context = { events: [], store: {}, username: 'User', setTab: () => undefined, busy: false } as unknown as TimelineRowContext;
      expect(renderToStaticMarkup(<TimelineRow item={items[0]} context={context} firstInTurn={false} last={false} />))
        .toContain('allow');

      // Built-in kinds keep their own nodes even while an extension is registered.
      const mixed = buildTimeline([
        claimed,
        { ...claimed, id: 'msg-1', sequence: 2, type: 'message.completed', data: { content: 'still renders' } },
      ]);
      expect(mixed.map((item) => item.kind)).toEqual(['extension', 'reply']);
    } finally {
      dispose();
    }
    expect(buildTimeline([claimed])).toEqual([]);
  });
});
