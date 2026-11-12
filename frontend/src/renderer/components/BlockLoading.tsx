import { cn } from '../ui/cn';

export interface BlockLoadingProps {
  /** Short block name, used to build the text ("正在加载<label>…"). */
  label?: string;
  /**
   * - `inline` — sits in the flow inside toolbars/headers
   * - `panel`  — fills the pane it replaces (centered spinner)
   * - `overlay`— floats centered above everything; no layout impact, used for
   *   dialogs/popovers/fullscreen overlays that only exist while open
   */
  variant?: 'inline' | 'panel' | 'overlay';
  className?: string;
}

/**
 * Loading placeholder for a `Suspense` boundary. Deliberately dependency-free:
 * a CSS-only spinner plus one line of text, so it can never fail to load.
 */
export function BlockLoading({ label, variant = 'inline', className }: BlockLoadingProps) {
  const text = label ? `正在加载${label}…` : '正在加载…';
  const spinner = (
    <span
      aria-hidden
      className={cn(
        'inline-block shrink-0 animate-spin rounded-full border-line-strong border-t-brand',
        variant === 'inline' ? 'size-3 border-2' : 'size-5 border-[2.5px]',
      )}
    />
  );

  if (variant === 'overlay') {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={cn('pointer-events-none fixed inset-0 z-[70] grid place-items-center', className)}
      >
        <div className="pop anim-pop flex items-center gap-2 rounded-xl px-3.5 py-2.5 text-[12.5px] text-fg-2">
          {spinner}
          <span>{text}</span>
        </div>
      </div>
    );
  }

  if (variant === 'panel') {
    return (
      <div
        role="status"
        aria-live="polite"
        aria-busy="true"
        className={cn('flex w-full flex-1 flex-col items-center justify-center gap-2.5 py-16 text-[12.5px] text-fg-3', className)}
      >
        {spinner}
        <span>{text}</span>
      </div>
    );
  }

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn('inline-flex items-center gap-1.5 px-1 py-1 text-[12px] text-fg-3', className)}
    >
      {spinner}
      <span>{text}</span>
    </div>
  );
}

export default BlockLoading;
