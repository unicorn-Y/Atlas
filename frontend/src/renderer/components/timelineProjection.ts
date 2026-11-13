import type { AgentEvent } from '../../types/runtime';
import { buildTimeline, type TimelineItem } from './timeline';

const NON_PROJECTING_EVENTS = new Set<AgentEvent['type']>([
  'run.phase', 'run.plan.updated', 'run.usage', 'run.todos', 'run.context.sources', 'run.context.warning', 'run.steered',
]);

/** Keeps a run's projection and folds adjacent streamed reply chunks into that reply node. */
export class TimelineProjection {
  private events: AgentEvent[] = [];
  private items: TimelineItem[] = [];

  project(events: AgentEvent[]): TimelineItem[] {
    let prefixLength = 0;
    const sharedLength = Math.min(this.events.length, events.length);
    while (prefixLength < sharedLength && this.events[prefixLength] === events[prefixLength]) prefixLength += 1;

    if (prefixLength !== this.events.length || events.length < this.events.length) {
      this.events = events.slice(0, prefixLength);
      this.items = buildTimeline(this.events);
    }

    for (const event of events.slice(prefixLength)) {
      this.events.push(event);
      if (!this.foldMessageDelta(event) && !NON_PROJECTING_EVENTS.has(event.type)) this.items = buildTimeline(this.events);
    }
    return this.items;
  }

  private foldMessageDelta(event: AgentEvent): boolean {
    if (event.type !== 'message.delta') return false;
    const last = this.items.at(-1);
    if (last?.kind !== 'reply' || !last.streaming) return false;
    const updated: TimelineItem = { ...last, content: last.content + String(event.data.content ?? '') };
    this.items = [...this.items.slice(0, -1), updated];
    return true;
  }
}
