// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/ToolCallBlocks/QueuedSummaryContent.tsx (Apache-2.0)
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';

export const SUMMARY_ROLL_TRANSITION_MS = 300;
export const SUMMARY_ROLL_HOLD_MS = 500;
export const SUMMARY_ROLL_TOTAL_MS = SUMMARY_ROLL_TRANSITION_MS + SUMMARY_ROLL_HOLD_MS;
const SUMMARY_ROLL_TIMER_DRIFT_SKIP_MS = 250;
const SUMMARY_ROLL_MAX_PENDING = 2;
const SUMMARY_ROLL_TRANSITION = { duration: SUMMARY_ROLL_TRANSITION_MS / 1000, ease: [0.4, 0, 0.2, 1] } as const;

function now() {
  return typeof performance !== 'undefined' ? performance.now() : Date.now();
}

/** When the main thread stalled, jump to the newest line instead of replaying stale ones. */
export function resolveQueuedSummaryPlaybackQueue<T>(queued: readonly T[], timerDriftMs: number): T[] {
  if (timerDriftMs > SUMMARY_ROLL_TIMER_DRIFT_SKIP_MS && queued.length > 1) return queued.slice(-1);
  return [...queued];
}

interface SummarySnapshot {
  key: string;
  refreshVersion?: string;
  primaryText: ReactNode;
  secondaryText?: ReactNode;
  trailingText?: ReactNode;
}

export function shouldRefreshQueuedSummaryContent(
  current: Pick<SummarySnapshot, 'key' | 'refreshVersion' | 'trailingText'>,
  next: Pick<SummarySnapshot, 'key' | 'refreshVersion' | 'trailingText'>,
) {
  return current.key === next.key
    && (current.trailingText !== next.trailingText || current.refreshVersion !== next.refreshVersion);
}

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return;
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return reduced;
}

/**
 * One-line summary that rolls vertically when its key changes (a new line of thought) and updates in
 * place when only its version changes (more tokens on the same line). At most the shown item plus two
 * pending ones; a late timer (busy main thread) skips straight to the newest.
 */
export function QueuedSummaryContent({ contentKey, contentRefreshVersion, primaryText, secondaryText, trailingText, enabled, disableAnimation = false }: {
  contentKey: string;
  contentRefreshVersion?: string;
  primaryText: ReactNode;
  secondaryText?: ReactNode;
  trailingText?: ReactNode;
  enabled: boolean;
  disableAnimation?: boolean;
}) {
  const reducedMotion = usePrefersReducedMotion();
  const shouldAnimate = enabled && !disableAnimation && !reducedMotion;
  const createSnapshot = (): SummarySnapshot => ({ key: contentKey, refreshVersion: contentRefreshVersion, primaryText, secondaryText, trailingText });
  const [displayed, setDisplayed] = useState(createSnapshot);
  const displayedRef = useRef(displayed);
  const queuedRef = useRef<SummarySnapshot[]>([]);
  const timerRef = useRef<number | null>(null);
  const animatingRef = useRef(false);

  useEffect(() => { displayedRef.current = displayed; }, [displayed]);

  useEffect(() => {
    const clearTimer = () => {
      if (timerRef.current !== null) { window.clearTimeout(timerRef.current); timerRef.current = null; }
    };
    const enqueue = (snapshot: SummarySnapshot) => {
      const queue = queuedRef.current;
      const existing = queue.findIndex((item) => item.key === snapshot.key);
      if (existing >= 0) {
        const next = [...queue];
        next[existing] = snapshot;
        queuedRef.current = next;
        return;
      }
      if (queue.length === 0) { queuedRef.current = [snapshot]; return; }
      // Three slots in total: shown, next, and one replaceable slot for the newest.
      queuedRef.current = [queue[0]!, snapshot].slice(0, SUMMARY_ROLL_MAX_PENDING);
    };
    const promote = (snapshot: SummarySnapshot) => {
      displayedRef.current = snapshot;
      setDisplayed(snapshot);
      animatingRef.current = true;
      clearTimer();
      const expectedAt = now() + SUMMARY_ROLL_TOTAL_MS;
      timerRef.current = window.setTimeout(() => {
        animatingRef.current = false;
        timerRef.current = null;
        const [nextQueued, ...rest] = resolveQueuedSummaryPlaybackQueue(queuedRef.current, now() - expectedAt);
        if (!nextQueued) { queuedRef.current = []; return; }
        queuedRef.current = rest;
        promote(nextQueued);
      }, SUMMARY_ROLL_TOTAL_MS);
    };
    const next = createSnapshot();

    if (!shouldAnimate) {
      clearTimer();
      animatingRef.current = false;
      queuedRef.current = [];
      displayedRef.current = next;
      setDisplayed(next);
      return;
    }
    if (displayedRef.current.key === next.key) {
      if (shouldRefreshQueuedSummaryContent(displayedRef.current, next)) {
        displayedRef.current = next;
        setDisplayed(next);
      }
      return;
    }
    if (animatingRef.current || queuedRef.current.length > 0) { enqueue(next); return; }
    promote(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [contentKey, contentRefreshVersion, shouldAnimate, trailingText]);

  useEffect(() => () => { if (timerRef.current !== null) window.clearTimeout(timerRef.current); }, []);

  if (!shouldAnimate) return <>{primaryText}{secondaryText}{trailingText}</>;

  return <span className="relative inline-flex min-w-0 items-center gap-2 overflow-hidden align-middle">
    <AnimatePresence initial={false} mode="popLayout">
      <motion.span key={displayed.key} className="inline-flex min-w-0 items-center gap-2"
        initial={{ y: '0.8em', opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: '-0.8em', opacity: 0 }}
        transition={SUMMARY_ROLL_TRANSITION}>
        {displayed.primaryText}
        {displayed.secondaryText}
      </motion.span>
    </AnimatePresence>
    {displayed.trailingText}
  </span>;
}
