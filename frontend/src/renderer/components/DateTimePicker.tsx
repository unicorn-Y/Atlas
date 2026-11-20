import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent, ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { ChevronLeft, ChevronRight, Clock3 } from 'lucide-react';

export interface DateTimePickerProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
}

type CalendarMonth = { year: number; month: number; focusDay: number };
type RectLike = { left: number; right: number; top: number; bottom: number };
type SizeLike = { width: number; height: number };
type ViewportLike = { width: number; height: number };
type PositionOptions = { side: 'top' | 'bottom'; align: 'start' | 'end'; gap: number; margin: number };
type ContainsTarget = { contains: (target: any) => boolean };

const WEEKDAYS = ['一', '二', '三', '四', '五', '六', '日'];
const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/;

export function computeAnchoredPosition(anchor: RectLike, panel: SizeLike, viewport: ViewportLike, options: PositionOptions): { left: number; top: number } {
  const maxLeft = Math.max(options.margin, viewport.width - panel.width - options.margin);
  const maxTop = Math.max(options.margin, viewport.height - panel.height - options.margin);
  const desiredLeft = options.align === 'end' ? anchor.right - panel.width : anchor.left;
  const desiredTop = options.side === 'top' ? anchor.top - options.gap - panel.height : anchor.bottom + options.gap;
  return {
    left: Math.min(Math.max(desiredLeft, options.margin), maxLeft),
    top: Math.min(Math.max(desiredTop, options.margin), maxTop),
  };
}

export function isInsidePopover(target: unknown, root: ContainsTarget | null, panel: ContainsTarget | null): boolean {
  return target !== null && target !== undefined
    && (root?.contains(target) === true || panel?.contains(target) === true);
}

function parseValue(value: string): { date: string; time: string } | null {
  const match = DATE_TIME.exec(value);
  if (!match) return null;
  const [, year, month, day, hour, minute] = match;
  const parsed = new Date(Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute));
  if (parsed.getFullYear() !== Number(year) || parsed.getMonth() !== Number(month) - 1 || parsed.getDate() !== Number(day)
      || parsed.getHours() !== Number(hour) || parsed.getMinutes() !== Number(minute)) return null;
  return { date: `${year}-${month}-${day}`, time: `${hour}:${minute}` };
}

function pad(value: number): string { return String(value).padStart(2, '0'); }
function isoDate(year: number, month: number, day: number): string { return `${year}-${pad(month + 1)}-${pad(day)}`; }
function daysInMonth(year: number, month: number): number { return new Date(Date.UTC(year, month + 1, 0)).getUTCDate(); }
function monthFromDate(date: string): CalendarMonth {
  const [year, month, day] = date.split('-').map(Number);
  return { year, month: month - 1, focusDay: day };
}
function todayDate(): string {
  const now = new Date();
  return isoDate(now.getFullYear(), now.getMonth(), now.getDate());
}

function TimeColumn({ label, value, options, onSelect, unit }: {
  label: string;
  value: string;
  options: string[];
  onSelect: (value: string) => void;
  unit: string;
}): ReactNode {
  return <div className="min-w-0">
    <span className="mb-1 block text-[10px] text-fg-3">{label}</span>
    <div role="listbox" aria-label={label} className="max-h-28 overflow-y-auto rounded-md border border-line bg-sunken p-1">
      {options.map((option) => <button
        key={option}
        type="button"
        role="option"
        aria-label={`${option}${unit}`}
        aria-selected={option === value}
        tabIndex={option === value ? 0 : -1}
        onClick={() => onSelect(option)}
        onKeyDown={(event) => {
          if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
          event.preventDefault();
          const offset = event.key === 'ArrowDown' ? 1 : -1;
          const index = options.indexOf(option);
          onSelect(options[(index + offset + options.length) % options.length]);
        }}
        className={`w-full rounded px-2 py-1 text-center text-[11px] ${option === value ? 'bg-brand text-white' : 'text-fg hover:bg-hover'}`}
      >{option}</button>)}
    </div>
  </div>;
}

export default function DateTimePicker({ label, value, onChange, required = false }: DateTimePickerProps): ReactNode {
  const parsed = parseValue(value);
  const [open, setOpen] = useState(false);
  const [clock, setClock] = useState(parsed?.time ?? '00:00');
  const [month, setMonth] = useState<CalendarMonth>(() => monthFromDate(parsed?.date ?? todayDate()));
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const dayRefs = useRef(new Map<number, HTMLButtonElement>());
  const [position, setPosition] = useState<{ left: number; top: number } | null>(null);
  const today = todayDate();

  useEffect(() => { if (parsed) setClock(parsed.time); }, [value]);

  useEffect(() => {
    if (!open || typeof document === 'undefined') return;
    const dismiss = (event: PointerEvent) => {
      if (!isInsidePopover(event.target, rootRef.current, panelRef.current)) setOpen(false);
    };
    document.addEventListener('pointerdown', dismiss);
    return () => document.removeEventListener('pointerdown', dismiss);
  }, [open]);

  useLayoutEffect(() => {
    if (!open || typeof window === 'undefined') { setPosition(null); return; }
    const place = () => {
      const anchor = triggerRef.current?.getBoundingClientRect();
      const panel = panelRef.current;
      if (!anchor || !panel) return;
      setPosition(computeAnchoredPosition(
        anchor,
        { width: panel.offsetWidth, height: panel.offsetHeight },
        { width: window.innerWidth, height: window.innerHeight },
        { side: 'bottom', align: 'start', gap: 4, margin: 12 },
      ));
    };
    place();
    window.addEventListener('scroll', place, true);
    window.addEventListener('resize', place);
    let observer: ResizeObserver | undefined;
    if (typeof ResizeObserver !== 'undefined' && panelRef.current) {
      observer = new ResizeObserver(place);
      observer.observe(panelRef.current);
    }
    return () => {
      observer?.disconnect();
      window.removeEventListener('scroll', place, true);
      window.removeEventListener('resize', place);
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    dayRefs.current.get(month.focusDay)?.focus();
  }, [open, month]);

  const monthTitle = useMemo(() => new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: 'long', timeZone: 'UTC',
  }).format(Date.UTC(month.year, month.month, 1)), [month.year, month.month]);
  const firstWeekday = (new Date(Date.UTC(month.year, month.month, 1)).getUTCDay() + 6) % 7;
  const dayCount = daysInMonth(month.year, month.month);
  const cellCount = Math.ceil((firstWeekday + dayCount) / 7) * 7;

  const shiftMonth = (delta: number) => setMonth((current) => {
    const absolute = current.year * 12 + current.month + delta;
    const year = Math.floor(absolute / 12);
    const nextMonth = absolute % 12;
    return { year, month: nextMonth, focusDay: Math.min(current.focusDay, daysInMonth(year, nextMonth)) };
  });
  const chooseDay = (day: number) => {
    const date = isoDate(month.year, month.month, day);
    setMonth((current) => ({ ...current, focusDay: day }));
    onChange(`${date}T${clock}`);
  };
  const chooseClockPart = (part: 0 | 1, next: string) => {
    const pieces = clock.split(':');
    pieces[part] = next;
    const nextClock = pieces.join(':');
    setClock(nextClock);
    if (parsed) onChange(`${parsed.date}T${nextClock}`);
  };
  const onDayKeyDown = (event: KeyboardEvent<HTMLButtonElement>, day: number) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      chooseDay(day);
      return;
    }
    const steps: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    const step = steps[event.key];
    if (!step) return;
    event.preventDefault();
    setMonth((current) => ({ ...current, focusDay: Math.min(Math.max(day + step, 1), dayCount) }));
  };
  const displayValue = parsed ? `${parsed.date} ${parsed.time}` : label;

  const popover = open && <div
    ref={panelRef}
    role="dialog"
    aria-label={label}
    onKeyDown={(event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        setOpen(false);
        triggerRef.current?.focus();
      }
    }}
    style={typeof document === 'undefined' ? undefined : {
      position: 'fixed', zIndex: 9999, left: position?.left ?? 0, top: position?.top ?? 0,
      visibility: position ? 'visible' : 'hidden',
    }}
    className="w-[19rem] rounded-xl border border-line bg-panel p-3 shadow-xl"
  >
      <div className="mb-2 flex items-center justify-between gap-2">
        <button type="button" aria-label="上个月" onClick={() => shiftMonth(-1)} className="grid size-8 place-items-center rounded-md hover:bg-sunken"><ChevronLeft size={16} /></button>
        <span aria-live="polite" data-calendar-month={`${month.year}-${pad(month.month + 1)}`} className="text-[12px] font-medium text-heading">{monthTitle}</span>
        <button type="button" aria-label="下个月" onClick={() => shiftMonth(1)} className="grid size-8 place-items-center rounded-md hover:bg-sunken"><ChevronRight size={16} /></button>
      </div>
      <div role="grid" aria-label={monthTitle} className="grid gap-1">
        <div role="row" className="grid grid-cols-7 gap-1">
          {WEEKDAYS.map((weekday) => <span key={weekday} role="columnheader" className="py-1 text-center text-[10px] text-fg-3">{weekday}</span>)}
        </div>
        {Array.from({ length: cellCount / 7 }, (_, week) => <div key={week} role="row" className="grid grid-cols-7 gap-1">
          {Array.from({ length: 7 }, (_, column) => {
            const day = week * 7 + column - firstWeekday + 1;
            if (day < 1 || day > dayCount) return <span key={`blank-${column}`} role="gridcell" aria-hidden="true" />;
            const date = isoDate(month.year, month.month, day);
            return <button
              key={day}
              ref={(node) => { if (node) dayRefs.current.set(day, node); else dayRefs.current.delete(day); }}
              type="button"
              role="gridcell"
              aria-label={`选择日期 ${date}`}
              aria-selected={parsed?.date === date}
              aria-current={today === date ? 'date' : undefined}
              tabIndex={day === month.focusDay ? 0 : -1}
              onClick={() => chooseDay(day)}
              onKeyDown={(event) => onDayKeyDown(event, day)}
              className={`grid aspect-square place-items-center rounded-md text-[11px] hover:bg-sunken ${parsed?.date === date ? 'bg-brand text-white' : 'text-fg'}`}
            >{day}</button>;
          })}
        </div>)}
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 border-t border-line pt-3">
        <TimeColumn label="小时" value={clock.slice(0, 2)} options={Array.from({ length: 24 }, (_, hour) => pad(hour))} unit="点" onSelect={(next) => chooseClockPart(0, next)} />
        <TimeColumn label="分钟" value={clock.slice(3, 5)} options={Array.from({ length: 60 }, (_, minute) => pad(minute))} unit="分" onSelect={(next) => chooseClockPart(1, next)} />
      </div>
    </div>;

  return <div ref={rootRef} className="relative inline-grid min-w-0 gap-1">
    <span className="text-[11px] text-fg-3">{label}</span>
    <button
      ref={triggerRef}
      type="button"
      aria-label={`选择${label}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      onClick={() => {
        if (!open) setMonth(monthFromDate(parsed?.date ?? todayDate()));
        setOpen((current) => !current);
      }}
      className="flex min-h-9 items-center justify-between gap-2 rounded-lg border border-line bg-sunken px-3 py-2 text-left text-[12px] text-fg"
    >
      <span>{displayValue}</span><Clock3 size={14} aria-hidden="true" />
    </button>
    {required && <input type="datetime-local" value={value} onChange={(event) => onChange(event.target.value)} required aria-hidden="true" tabIndex={-1} className="sr-only" />}
    {open && typeof document === 'undefined' && popover}
    {open && typeof document !== 'undefined' && createPortal(popover, document.body)}
  </div>;
}
