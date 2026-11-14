import type { AgentEvent } from '../../types/runtime';
import { createTimelineAssembler, type TimelineItem } from './timeline';

/** Replay consecutive chunks once while retaining the first chunk's stable node identity. */
export function compactTimelineReplay(events: readonly AgentEvent[]): AgentEvent[] {
  const compacted: AgentEvent[] = [];
  for (const event of events) {
    const previous = compacted.at(-1);
    if (event.type === 'message.delta' && previous?.type === 'message.delta' && previous.runId === event.runId) {
      compacted[compacted.length - 1] = {
        ...previous,
        data: { ...previous.data, content: String(previous.data.content ?? '') + String(event.data.content ?? '') },
      };
    } else compacted.push(event);
  }
  return compacted;
}

const sameEvent = (left: AgentEvent, right: AgentEvent) => left === right || (
  left.id === right.id && left.runId === right.runId && left.sequence === right.sequence
  && left.type === right.type && left.timestamp === right.timestamp && JSON.stringify(left.data) === JSON.stringify(right.data)
);

/** Keeps a run's projection and folds adjacent streamed reply chunks into that reply node. */
export class TimelineProjection {
  private events: AgentEvent[] = [];
  private items: TimelineItem[] = [];
  private assembler = createTimelineAssembler();

  project(events: AgentEvent[]): TimelineItem[] {
    let prefixLength = 0;
    const sharedLength = Math.min(this.events.length, events.length);
    while (prefixLength < sharedLength && sameEvent(this.events[prefixLength], events[prefixLength])) prefixLength += 1;

    if (prefixLength !== this.events.length || events.length < this.events.length) {
      this.events = events.slice(0, prefixLength);
      this.assembler = createTimelineAssembler();
      this.assembler.append(compactTimelineReplay(this.events));
    }

    const incoming = events.slice(prefixLength);
    this.events.push(...incoming);
    const projected = this.assembler.append(compactTimelineReplay(incoming));
    const previous = new Map(this.items.map((item) => [item.id, item]));
    const updated = projected.map((item) => {
      const existing = previous.get(item.id);
      // The reducer mutates its open nodes. Published snapshots stay immutable for React's memoized rows.
      return existing && JSON.stringify(existing) === JSON.stringify(item) ? existing : structuredClone(item);
    });
    if (updated.length !== this.items.length || updated.some((item, index) => item !== this.items[index])) this.items = updated;
    return this.items;
  }
}
