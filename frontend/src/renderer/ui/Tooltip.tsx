import { cloneElement, createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { MouseEvent, ReactElement, ReactNode } from 'react';
import * as T from '@radix-ui/react-tooltip';
import { pointerModality } from './inputModality';

export const TooltipProvider = ({ children }: { children: ReactNode }) =>
  <T.Provider delayDuration={0} skipDelayDuration={0}>{children}</T.Provider>;

type TipLabel = ReactNode | (() => ReactNode);
const TooltipSuppression = createContext<((suppressed: boolean) => void) | null>(null);

/** Hover hint for icon-only controls. The child must accept a ref (a button). */
export function Tip({ label, side = 'bottom', openOnClick = false, disabled = false, align = 'center', delayMs, focusDelayMs = 0, gap = 6, maxWidth, shortcutKeys, portal = true, children }: {
  label: TipLabel;
  side?: 'top' | 'bottom' | 'left' | 'right';
  openOnClick?: boolean;
  disabled?: boolean;
  align?: 'center' | 'end';
  delayMs?: number;
  focusDelayMs?: number;
  gap?: number;
  maxWidth?: number;
  shortcutKeys?: readonly string[];
  portal?: boolean;
  children: ReactElement<{ onClick?: (event: MouseEvent) => void; onFocus?: (event: React.FocusEvent) => void; onBlur?: (event: React.FocusEvent) => void; onMouseLeave?: (event: React.MouseEvent) => void; onPointerMove?: (event: React.PointerEvent) => void; onPointerLeave?: (event: React.PointerEvent) => void }>;
}) {
  const [pinned, setPinned] = useState(false);
  const [hoverOpen, setHoverOpen] = useState(false);
  const [focusOpen, setFocusOpen] = useState(false);
  const [suppressed, setSuppressed] = useState(false);
  const suppressParent = useContext(TooltipSuppression);
  const rootRef = useRef<HTMLSpanElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const focusTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const hovering = useRef(false);
  const open = disabled ? false : (openOnClick && pinned) || hoverOpen || focusOpen;
  const visible = open && !suppressed;
  const resolvedLabel = visible ? (typeof label === 'function' ? label() : label) : null;
  const labelText = typeof resolvedLabel === 'string' ? resolvedLabel : '';
  const shortcutText = shortcutKeys?.join(' ') ?? '';
  const dismissPinned = () => { setPinned(false); setHoverOpen(false); };
  const cancelFocusTimer = () => {
    if (focusTimer.current === null) return;
    clearTimeout(focusTimer.current);
    focusTimer.current = null;
  };
  const cancelHoverTimer = () => {
    if (hoverTimer.current === null) return;
    clearTimeout(hoverTimer.current);
    hoverTimer.current = null;
  };
  const cancelTimers = () => { cancelFocusTimer(); cancelHoverTimer(); };
  const dismissAll = useCallback(() => {
    if (focusTimer.current !== null) clearTimeout(focusTimer.current);
    if (hoverTimer.current !== null) clearTimeout(hoverTimer.current);
    focusTimer.current = null;
    hoverTimer.current = null;
    hovering.current = false;
    setPinned(false);
    setHoverOpen(false);
    setFocusOpen(false);
  }, []);
  const showFromFocus = () => {
    setFocusOpen(true);
    if (hovering.current) setHoverOpen(true);
  };

  useEffect(() => {
    if (disabled) {
      dismissPinned();
      setFocusOpen(false);
      hovering.current = false;
      cancelTimers();
    } else if (!openOnClick) setPinned(false);
    return cancelTimers;
  }, [disabled, openOnClick]);

  useEffect(() => {
    suppressParent?.(visible);
    return () => { suppressParent?.(false); };
  }, [suppressParent, visible]);

  useEffect(() => {
    if (!openOnClick || !visible || disabled) return;
    const outside = (event: PointerEvent) => {
      if (!(event.target instanceof Node)) return;
      if (!rootRef.current?.contains(event.target) && !contentRef.current?.contains(event.target)) dismissAll();
    };
    document.addEventListener('pointerdown', outside);
    return () => { document.removeEventListener('pointerdown', outside); };
  }, [disabled, dismissAll, openOnClick, visible]);

  useEffect(() => {
    if (!visible || disabled) return;
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        dismissAll();
      } else if (event.key === 'Tab' && openOnClick && pinned) dismissAll();
    };
    document.addEventListener('keydown', keydown, true);
    return () => { document.removeEventListener('keydown', keydown, true); };
  }, [disabled, dismissAll, openOnClick, pinned, visible]);

  const anchor = cloneElement(children, {
    onClick: (event: MouseEvent) => {
      children.props.onClick?.(event);
      cancelTimers();
      hovering.current = false;
      setFocusOpen(false);
      setHoverOpen(false);
      if (!openOnClick) return;
      if (event.target !== event.currentTarget) return;
      if (disabled) return;
      if (pinned) dismissPinned();
      else setPinned(true);
    },
    onFocus: (event) => {
      children.props.onFocus?.(event);
      const childPrevented = event.defaultPrevented;
      event.preventDefault(); // Radix otherwise applies the hover delay to focus too.
      cancelTimers();
      if (childPrevented || disabled || pointerModality()) return;
      if (focusDelayMs <= 0) showFromFocus();
      else focusTimer.current = setTimeout(() => { focusTimer.current = null; showFromFocus(); }, focusDelayMs);
    },
    onBlur: (event) => {
      children.props.onBlur?.(event);
      cancelFocusTimer();
      setFocusOpen(false);
    },
    onPointerMove: (event) => {
      children.props.onPointerMove?.(event);
      const childPrevented = event.defaultPrevented;
      event.preventDefault(); // Hover timing is owned here, not by Radix's shared provider timer.
      if (childPrevented || disabled || event.pointerType === 'touch' || hovering.current) return;
      hovering.current = true;
      cancelHoverTimer();
      if ((delayMs ?? 0) <= 0) setHoverOpen(true);
      else hoverTimer.current = setTimeout(() => { hoverTimer.current = null; setHoverOpen(true); }, delayMs);
    },
    onPointerLeave: (event) => {
      children.props.onPointerLeave?.(event);
      event.preventDefault();
      hovering.current = false;
      cancelHoverTimer();
      if (!openOnClick || !pinned) {
        setFocusOpen(false);
        setHoverOpen(false);
      }
    },
    onMouseLeave: (event) => {
      children.props.onMouseLeave?.(event);
      cancelTimers();
      hovering.current = false;
      if (!openOnClick || !pinned) {
        setFocusOpen(false);
        setHoverOpen(false);
      }
    },
  });
  const content = <T.Content
    ref={contentRef}
    side={side}
    align={align}
    sideOffset={gap}
    aria-label={[labelText, shortcutText].filter(Boolean).join(' ') || undefined}
    style={maxWidth === undefined ? undefined : { maxWidth }}
    className="pop anim-fade z-[70] rounded-lg px-2.5 py-1 text-[12px] text-fg"
  >
    {resolvedLabel && <span>{resolvedLabel}</span>}
    {shortcutKeys && shortcutKeys.length > 0 && <span aria-hidden="true" className={`ml-2 inline-flex items-center gap-0.5 text-[10px] ${shortcutKeys.includes('+') ? 'rounded bg-white/10 px-1' : ''}`}>
      {shortcutKeys.map((key, index) => key === '+' ? <span key={`${key}-${index}`}>+</span> : <kbd key={`${key}-${index}`} className="inline-flex min-w-4 justify-center rounded bg-white/10 px-0.5 font-sans">{key}</kbd>)}
    </span>}
  </T.Content>;

  return <TooltipSuppression.Provider value={setSuppressed}>
    <span ref={rootRef} className="contents">
      <T.Root open={visible} onOpenChange={(next) => { if (!disabled) setHoverOpen(next); }} delayDuration={0}>
        <T.Trigger asChild>{anchor}</T.Trigger>
        {portal ? <T.Portal>{content}</T.Portal> : content}
      </T.Root>
    </span>
  </TooltipSuppression.Provider>;
}
