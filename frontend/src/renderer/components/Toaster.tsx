import { useCallback, useEffect, useRef, useState } from 'react';
import { CircleAlert, CircleCheck, Info, TriangleAlert, X } from 'lucide-react';
import { cn } from '../ui/cn';

export type ToastLevel = 'info' | 'success' | 'error' | 'warn';

export interface ToastItem {
  id: number;
  message: string;
  level: ToastLevel;
  /** When the toast (re)appeared; deduped repeats push this forward. */
  createdAt: number;
  /** 1 = first appearance, 2+ = the same message fired again. */
  repeat: number;
}

/** Old single-toast behaviour dismissed after 2200ms; keep that as the default. */
export const DEFAULT_TOAST_DURATION = 2200;
/** How many toasts may be visible at once; the oldest is dropped beyond this. */
export const MAX_TOASTS = 5;

/**
 * A tiny FIFO toast queue.
 *
 * - identical messages dedupe into one item (bumped in place, timer restarted)
 * - every item auto-expires after `duration`ms, and can be closed by hand
 * - at most `MAX_TOASTS` items are kept, oldest evicted first
 */
export function useToastQueue(duration: number = DEFAULT_TOAST_DURATION) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const itemsRef = useRef<ToastItem[]>([]);
  const nextId = useRef(1);
  const timers = useRef(new Map<number, number>());

  // The ref is the source of truth for reads inside callbacks, so a burst of
  // pushes in one tick cannot clobber each other through stale state.
  const commit = useCallback((next: ToastItem[]) => {
    itemsRef.current = next;
    setItems(next);
  }, []);

  const clearTimer = useCallback((id: number) => {
    const handle = timers.current.get(id);
    if (handle !== undefined) {
      window.clearTimeout(handle);
      timers.current.delete(id);
    }
  }, []);

  const dismiss = useCallback(
    (id: number) => {
      clearTimer(id);
      commit(itemsRef.current.filter((item) => item.id !== id));
    },
    [clearTimer, commit],
  );

  const clear = useCallback(() => {
    timers.current.forEach((handle) => window.clearTimeout(handle));
    timers.current.clear();
    commit([]);
  }, [commit]);

  const push = useCallback(
    (message: string, level: ToastLevel = 'info', ttl: number = duration) => {
      const text = String(message ?? '').trim();
      if (!text) return;

      const current = itemsRef.current;
      const existing = current.find((item) => item.message === text);
      let id: number;

      if (existing) {
        id = existing.id;
        clearTimer(id);
        commit(
          current.map((item) =>
            item.id === id
              ? { ...item, level, createdAt: Date.now(), repeat: Math.min(item.repeat + 1, 99) }
              : item,
          ),
        );
      } else {
        id = nextId.current++;
        const next = [...current, { id, message: text, level, createdAt: Date.now(), repeat: 1 }];
        while (next.length > MAX_TOASTS) {
          const dropped = next.shift();
          if (dropped) clearTimer(dropped.id);
        }
        commit(next);
      }

      if (ttl > 0) {
        timers.current.set(
          id,
          window.setTimeout(() => dismiss(id), ttl),
        );
      }
    },
    [clearTimer, commit, dismiss, duration],
  );

  useEffect(
    () => () => {
      timers.current.forEach((handle) => window.clearTimeout(handle));
      timers.current.clear();
    },
    [],
  );

  return { items, push, dismiss, clear };
}

const LEVEL_ICON = {
  info: Info,
  success: CircleCheck,
  error: CircleAlert,
  warn: TriangleAlert,
} as const;

const LEVEL_TONE: Record<ToastLevel, string> = {
  info: 'text-fg-2',
  success: 'text-ok',
  error: 'text-danger',
  warn: 'text-warn',
};

export interface ToasterProps {
  items: ToastItem[];
  onDismiss: (id: number) => void;
  className?: string;
}

/** Renders the toast queue bottom-center, above dialogs. */
export function Toaster({ items, onDismiss, className }: ToasterProps) {
  if (items.length === 0) return null;

  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className={cn(
        'pointer-events-none fixed bottom-7 left-1/2 z-[80] flex w-[min(28rem,calc(100vw-2rem))] -translate-x-1/2 flex-col items-stretch gap-2',
        className,
      )}
    >
      {items.map((item) => {
        const Icon = LEVEL_ICON[item.level];
        return (
          <div
            key={item.id}
            role={item.level === 'error' ? 'alert' : 'status'}
            className="pop anim-pop pointer-events-auto flex items-start gap-2 rounded-xl px-3.5 py-2.5 text-[13.5px] text-fg"
          >
            <Icon className={cn('mt-0.5 size-4 shrink-0', LEVEL_TONE[item.level])} aria-hidden />
            <span className="min-w-0 flex-1 break-words leading-[1.45]">{item.message}</span>
            {item.repeat > 1 ? (
              <span className="mt-0.5 shrink-0 rounded-full bg-hover px-1.5 text-[11px] tabular-nums text-fg-3">
                ×{item.repeat}
              </span>
            ) : null}
            <button
              type="button"
              aria-label="关闭提示"
              onClick={() => onDismiss(item.id)}
              className="-mr-1 mt-0.5 inline-flex size-5 shrink-0 items-center justify-center rounded text-fg-3 hover:bg-hover hover:text-fg"
            >
              <X className="size-3.5" aria-hidden />
            </button>
          </div>
        );
      })}
    </div>
  );
}

export default Toaster;
