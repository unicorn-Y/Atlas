import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import {
  registerConversationNode,
  TimelineRow,
  type TimelineRowContext,
} from './ConversationActivity';
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
});
