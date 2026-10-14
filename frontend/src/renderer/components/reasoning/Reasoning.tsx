// Ported from zai-org/ZCode@aac4755666d09fdcd70272fcf063c077a639015f: packages/ui/src/components/ai-elements/reasoning.tsx (Apache-2.0)
// (itself derived from vercel/ai-elements reasoning.tsx, Apache-2.0). Atlas changes: Chinese labels
// inline instead of intl, Atlas theme tokens, a local controllable-state hook, Radix Collapsible direct.
import * as CollapsiblePrimitive from '@radix-ui/react-collapsible';
import { Brain, ChevronRight } from 'lucide-react';
import {
  createContext, memo, useCallback, useContext, useEffect, useMemo, useRef, useState,
  type ComponentProps, type CSSProperties, type ReactNode,
} from 'react';
import { cn } from '../../ui/cn';
import { QueuedSummaryContent } from './QueuedSummaryContent';
import {
  EMPTY_SCROLL_MASK_STATE, getVerticalScrollMaskStyle, resolveVerticalScrollMaskState,
  type ScrollMaskState, type ScrollMetrics,
} from './scrollMask';

interface ReasoningContextValue {
  isStreaming: boolean;
  isOpen: boolean;
  shouldRenderContent: boolean;
  setIsOpen: (open: boolean) => void;
  duration: number | undefined;
}

const ReasoningContext = createContext<ReasoningContextValue | null>(null);

export const useReasoning = () => {
  const context = useContext(ReasoningContext);
  if (!context) throw new Error('Reasoning components must be used within Reasoning');
  return context;
};

/** Minimal stand-in for @radix-ui/react-use-controllable-state: a prop wins over local state. */
function useControllable<T>(prop: T | undefined, defaultProp: T, onChange?: (value: T) => void): [T, (value: T) => void] {
  const [local, setLocal] = useState(defaultProp);
  const value = prop !== undefined ? prop : local;
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const set = useCallback((next: T) => {
    if (prop === undefined) setLocal(next);
    onChangeRef.current?.(next);
  }, [prop]);
  return [value, set];
}

export type ReasoningProps = Omit<ComponentProps<typeof CollapsiblePrimitive.Root>, 'open' | 'defaultOpen' | 'onOpenChange'> & {
  isStreaming?: boolean;
  /** Changing to a new non-null key collapses the block unless the reader already toggled it. */
  autoCollapseKey?: string | number | null;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Seconds, when the caller knows the real thinking span (from event timestamps). */
  duration?: number;
};

const MS_IN_S = 1000;
const REASONING_CONTENT_COLLAPSE_UNMOUNT_DELAY_MS = 300;
const REASONING_BOTTOM_LOCK_DISTANCE_PX = 2;

export function shouldAutoCollapseReasoning({ autoCollapseKey, previousAutoCollapseKey, userInteracted }: {
  autoCollapseKey: string | number | null | undefined;
  previousAutoCollapseKey: string | number | null | undefined;
  userInteracted: boolean;
}) {
  return autoCollapseKey != null && autoCollapseKey !== previousAutoCollapseKey && !userInteracted;
}

export function isReasoningScrollAtBottom({ clientHeight, scrollHeight, scrollTop }: ScrollMetrics) {
  return Math.max(0, scrollHeight - clientHeight - scrollTop) <= REASONING_BOTTOM_LOCK_DISTANCE_PX;
}

export const Reasoning = memo(({ className, isStreaming = false, autoCollapseKey = null, open, defaultOpen = false, onOpenChange, duration: durationProp, children, ...props }: ReasoningProps) => {
  const isOpenControlled = open !== undefined;
  const [isOpen, setIsOpen] = useControllable<boolean>(open, defaultOpen, onOpenChange);
  const [measuredDuration, setMeasuredDuration] = useState<number | undefined>(undefined);
  const duration = durationProp ?? measuredDuration;

  const startTimeRef = useRef<number | null>(null);
  const unmountDelayRef = useRef<number | null>(null);
  const userInteractedRef = useRef(false);
  const previousAutoCollapseKeyRef = useRef<string | number | null>(null);
  const [shouldRenderContent, setShouldRenderContent] = useState(() => isOpen);
  const handleOpenChange = useCallback((nextOpen: boolean) => {
    userInteractedRef.current = true;
    if (nextOpen) setShouldRenderContent(true);
    setIsOpen(nextOpen);
  }, [setIsOpen]);

  useEffect(() => {
    if (!isStreaming) {
      if (startTimeRef.current !== null) setMeasuredDuration(Math.ceil((Date.now() - startTimeRef.current) / MS_IN_S));
      startTimeRef.current = null;
      return;
    }
    if (startTimeRef.current === null) startTimeRef.current = Date.now();
    // Collapsed, the live summary is enough: don't re-render the whole block every second for a
    // hidden duration. Once opened, recompute from the same start and keep ticking.
    if (!isOpen) return;
    const update = () => {
      if (startTimeRef.current === null) return;
      setMeasuredDuration(Math.max(1, Math.ceil((Date.now() - startTimeRef.current) / MS_IN_S)));
    };
    update();
    const timer = window.setInterval(update, MS_IN_S);
    return () => window.clearInterval(timer);
  }, [isOpen, isStreaming]);

  useEffect(() => {
    const previous = previousAutoCollapseKeyRef.current;
    previousAutoCollapseKeyRef.current = autoCollapseKey;
    if (isOpenControlled) return;
    // The end of thinking collapses it, but never over a choice the reader already made.
    if (shouldAutoCollapseReasoning({ autoCollapseKey, previousAutoCollapseKey: previous, userInteracted: userInteractedRef.current })) {
      setIsOpen(false);
    }
  }, [autoCollapseKey, isOpenControlled, setIsOpen]);

  useEffect(() => {
    if (isOpen) {
      if (unmountDelayRef.current !== null) { window.clearTimeout(unmountDelayRef.current); unmountDelayRef.current = null; }
      setShouldRenderContent(true);
      return;
    }
    if (!shouldRenderContent) return;
    // Keep the children mounted until the 300ms collapse animation has measured and finished,
    // then drop the heavy DOM.
    unmountDelayRef.current = window.setTimeout(() => { setShouldRenderContent(false); unmountDelayRef.current = null; },
      REASONING_CONTENT_COLLAPSE_UNMOUNT_DELAY_MS);
    return () => {
      if (unmountDelayRef.current !== null) { window.clearTimeout(unmountDelayRef.current); unmountDelayRef.current = null; }
    };
  }, [isOpen, shouldRenderContent]);

  useEffect(() => () => { if (unmountDelayRef.current !== null) window.clearTimeout(unmountDelayRef.current); }, []);

  const contextValue = useMemo(() => ({ duration, isOpen, isStreaming, setIsOpen, shouldRenderContent }),
    [duration, isOpen, isStreaming, setIsOpen, shouldRenderContent]);

  return <ReasoningContext.Provider value={contextValue}>
    <CollapsiblePrimitive.Root className={cn('not-prose flex flex-col', className)} onOpenChange={handleOpenChange} open={isOpen} {...props}>
      {children}
    </CollapsiblePrimitive.Root>
  </ReasoningContext.Provider>;
});

export function resolveReasoningStreamingSummary(streamingText: string): { key: string; text: string } | null {
  const lines = streamingText.replace(/\r\n?/gu, '\n').split('\n');
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const text = lines[index]?.trim() ?? '';
    if (text.length > 0) return { key: String(index), text: text.replace(/\*\*/g, '') };
  }
  return null;
}

const REASONING_SUMMARY_MASK = 'linear-gradient(to right, transparent 0, black 16px, black calc(100% - 16px), transparent 100%)';

function summaryMaskStyle(overflowing: boolean): CSSProperties | undefined {
  if (!overflowing) return undefined;
  return {
    WebkitMaskImage: REASONING_SUMMARY_MASK, maskImage: REASONING_SUMMARY_MASK,
    WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat', WebkitMaskSize: '100% 100%', maskSize: '100% 100%',
  };
}

function finishedLabel(duration: number | undefined): ReactNode {
  return <span className="inline-flex items-center gap-2">
    <span className="font-medium text-fg-3">思考</span>
    <span className="font-normal text-fg-3">·</span>
    <span className="font-normal text-fg-3">{duration === undefined ? '持续了几秒' : `持续了 ${duration} 秒`}</span>
  </span>;
}

export type ReasoningTriggerProps = ComponentProps<typeof CollapsiblePrimitive.Trigger> & {
  getThinkingMessage?: (isStreaming: boolean, duration?: number) => ReactNode;
  streamingText?: string;
};

export const ReasoningTrigger = memo(({ className, children, getThinkingMessage, streamingText = '', ...props }: ReasoningTriggerProps) => {
  const { isStreaming, isOpen, duration } = useReasoning();
  const summary = isStreaming && !isOpen ? resolveReasoningStreamingSummary(streamingText) : null;
  const viewportRef = useRef<HTMLSpanElement | null>(null);
  const textRef = useRef<HTMLSpanElement | null>(null);
  const [overflowing, setOverflowing] = useState(false);

  useEffect(() => {
    const viewport = viewportRef.current;
    if (!viewport || !summary) return;
    const sync = () => {
      setOverflowing((current) => {
        const next = viewport.scrollWidth > viewport.clientWidth + 1;
        return current === next ? current : next;
      });
      // A plain overflow-hidden would pin the old prefix; push the one-line viewport to its end so
      // the newest tokens stay visible and older words slide off to the left.
      viewport.scrollLeft = viewport.scrollWidth;
    };
    sync();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(sync);
    observer.observe(viewport);
    if (textRef.current) observer.observe(textRef.current);
    return () => observer.disconnect();
  }, [summary?.text]);

  const label = getThinkingMessage?.(isStreaming, duration)
    ?? (isStreaming && !isOpen ? <span className="text-shimmer font-medium">正在思考</span> : finishedLabel(duration));

  return <CollapsiblePrimitive.Trigger
    className={cn('group/reasoning inline-flex max-w-full min-w-0 items-center gap-2 self-start text-[13px] transition-colors', className)}
    {...props}>
    {children ?? <>
      {/* Static icon: a spinner would keep repainting for the whole of a long streamed reply. */}
      <Brain className="size-4 shrink-0 text-fg-3" aria-hidden="true" />
      {/* Fixed-width label; only the summary flexes, so a long summary can't wrap the label. */}
      <span className="shrink-0 whitespace-nowrap">{label}</span>
      {summary && <span className="shrink-0 text-fg-3">·</span>}
      {summary && <span ref={viewportRef} className="min-w-0 flex-1 overflow-hidden whitespace-nowrap text-fg-2" style={summaryMaskStyle(overflowing)}>
        <QueuedSummaryContent contentKey={`reasoning-line:${summary.key}`} contentRefreshVersion={summary.text} enabled
          primaryText={<span ref={textRef} className="inline-block min-w-max">{summary.text}</span>} />
      </span>}
      <ChevronRight aria-hidden="true" className={cn('size-4 shrink-0 text-fg-3 transition-[opacity,transform]',
        isOpen ? 'rotate-90 opacity-100' : 'rotate-0 opacity-0 group-hover/reasoning:opacity-100')} />
    </>}
  </CollapsiblePrimitive.Trigger>;
});

export type ReasoningContentProps = Omit<ComponentProps<typeof CollapsiblePrimitive.Content>, 'children'> & {
  children: string;
  variant?: 'default' | 'nested';
  footer?: ReactNode;
};

export const ReasoningContent = memo(({ className, children, forceMount, variant = 'default', footer, ...props }: ReasoningContentProps) => {
  const { isOpen, shouldRenderContent } = useReasoning();
  const renderChildren = isOpen || shouldRenderContent || Boolean(forceMount);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const followBottomRef = useRef(true);
  const [mask, setMask] = useState<ScrollMaskState>(EMPTY_SCROLL_MASK_STATE);
  const updateMask = useCallback(() => {
    const node = scrollRef.current;
    setMask(node ? resolveVerticalScrollMaskState(node) : EMPTY_SCROLL_MASK_STATE);
  }, []);
  const scrollToBottom = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
    updateMask();
  }, [updateMask]);
  const handleScroll = useCallback(() => {
    const node = scrollRef.current;
    if (!node) return;
    followBottomRef.current = isReasoningScrollAtBottom(node);
    updateMask();
  }, [updateMask]);

  useEffect(() => {
    if (!renderChildren) { followBottomRef.current = true; setMask(EMPTY_SCROLL_MASK_STATE); return; }
    const node = scrollRef.current;
    if (!node || typeof ResizeObserver === 'undefined') {
      if (followBottomRef.current) scrollToBottom(); else updateMask();
      return;
    }
    // Follow the newest thought while it streams; pause once the reader scrolls up, resume at the bottom.
    const sync = () => { if (followBottomRef.current) scrollToBottom(); else updateMask(); };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(node);
    if (contentRef.current) observer.observe(contentRef.current);
    return () => observer.disconnect();
  }, [scrollToBottom, renderChildren, updateMask]);

  useEffect(() => {
    if (!renderChildren) return;
    if (followBottomRef.current) scrollToBottom(); else updateMask();
  }, [children, scrollToBottom, renderChildren, updateMask]);

  return <CollapsiblePrimitive.Content forceMount={forceMount} className={cn('reasoning-collapsible', className)} {...props}>
    <div className="reasoning-collapsible-fade">
      {renderChildren ? <div className="pt-3">
        <div ref={scrollRef} onScroll={handleScroll} style={getVerticalScrollMaskStyle(mask)}
          className={cn('max-h-60 space-y-2 overflow-auto text-[13px] text-fg-3', variant === 'default' && 'ml-2 border-l border-line pl-3.5')}>
          {/* Plain text on purpose: re-parsing Markdown on every streamed chunk gets slower the longer the thought. */}
          <div ref={contentRef} className="min-w-0 whitespace-pre-wrap break-words leading-[1.7] text-fg-3">{children}</div>
        </div>
        {footer}
      </div> : null}
    </div>
  </CollapsiblePrimitive.Content>;
});

Reasoning.displayName = 'Reasoning';
ReasoningTrigger.displayName = 'ReasoningTrigger';
ReasoningContent.displayName = 'ReasoningContent';
