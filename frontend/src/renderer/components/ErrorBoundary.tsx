import { Component, Fragment, useState, type ErrorInfo, type ReactNode } from 'react';
import { CircleCheck, RotateCcw, TriangleAlert } from 'lucide-react';
import { cn } from '../ui/cn';

/** Render-prop payload handed to `fallback` when it is a function. */
export interface ErrorBoundaryFallbackArgs {
  error: Error;
  reset: () => void;
}

/**
 * A static node (rendered as-is) or a function receiving the caught error and
 * the `reset` callback (which clears the error state *and* remounts children).
 */
export type ErrorBoundaryFallback = ReactNode | ((args: ErrorBoundaryFallbackArgs) => ReactNode);

export interface ErrorBoundaryProps {
  children: ReactNode;
  /** Custom fallback. Defaults to the built-in "这块加载失败" panel. */
  fallback?: ErrorBoundaryFallback;
  /** Called from `componentDidCatch`, after the error is logged. */
  onError?: (error: Error, info: ErrorInfo) => void;
  /** Short name of the block, shown in the default fallback ("对话面板加载失败"). */
  label?: string;
  /** Inline, low-profile layout for menus / dialogs / badges. */
  compact?: boolean;
  className?: string;
}

interface ErrorBoundaryState {
  error: Error | null;
  /** Bumped on retry so the subtree is unmounted and mounted again. */
  resetKey: number;
}

function errorMessage(error: Error): string {
  const message = typeof error.message === 'string' ? error.message.trim() : '';
  return message || String(error);
}

function detailsText(error: Error, info: string | null): string {
  const head = `${error.name}: ${errorMessage(error)}`;
  return info ? `${head}\n${info}` : head;
}

/** Default fallback: a small self-contained card with retry + collapsible details. */
function LoadFailedFallback({
  error,
  info,
  label,
  compact,
  reset,
}: {
  error: Error;
  info: string | null;
  label?: string;
  compact?: boolean;
  reset: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const title = '这块加载失败';

  const copy = () => {
    const text = detailsText(error, info);
    void navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1600);
      },
      () => setCopied(false),
    );
  };

  return (
    <div
      role="alert"
      aria-live="polite"
      className={cn(
        'flex flex-col gap-2 rounded-xl border border-line bg-sunken/70 text-fg',
        compact ? 'px-3 py-2.5' : 'px-4 py-3.5',
      )}
    >
      <div className="flex items-start gap-2.5">
        <TriangleAlert className={cn('mt-0.5 shrink-0 text-warn', compact ? 'size-4' : 'size-[18px]')} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className={cn('font-medium text-fg', compact ? 'text-[12.5px]' : 'text-[13.5px]')}>
            {title}
            {label ? <span className="text-fg-3"> · {label}</span> : null}
          </div>
          <div className={cn('mt-0.5 text-fg-3', compact ? 'text-[11.5px]' : 'text-[12.5px]')}>
            可以重试；如果一直失败，展开详情看原因。
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={reset}
          className="inline-flex h-7 items-center gap-1.5 rounded-lg bg-brand px-2.5 text-[12.5px] font-medium text-on-primary hover:brightness-[1.06]"
        >
          <RotateCcw className="size-3.5" aria-hidden />
          重试
        </button>
        <button
          type="button"
          onClick={() => setOpen((value) => !value)}
          aria-expanded={open}
          className="inline-flex h-7 items-center rounded-lg px-2.5 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg"
        >
          {open ? '收起详情' : '查看详情'}
        </button>
        {open ? (
          <button
            type="button"
            onClick={copy}
            className="inline-flex h-7 items-center gap-1.5 rounded-lg px-2.5 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg"
          >
            {copied ? <CircleCheck className="size-3.5 text-ok" aria-hidden /> : null}
            {copied ? '已复制' : '复制错误信息'}
          </button>
        ) : null}
      </div>

      {open ? (
        <div className="rounded-lg bg-code p-2.5">
          <div className="text-[12px] font-medium text-fg-2">{errorMessage(error)}</div>
          <pre className="mt-1.5 max-h-40 overflow-auto whitespace-pre-wrap break-words font-mono text-[11px] leading-[1.5] text-fg-3">
            {detailsText(error, info)}
          </pre>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Catches render/lifecycle errors below it so one broken block cannot take down
 * the whole app. Retrying clears the error and remounts the subtree by key.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, resetKey: 0 };

  private info: string | null = null;

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    this.info = info.componentStack ?? null;
    console.error(`[ErrorBoundary] ${this.props.label ?? 'block'} crashed:`, error, info.componentStack);
    try {
      this.props.onError?.(error, info);
    } catch (reportingError) {
      console.error('[ErrorBoundary] onError handler threw:', reportingError);
    }
  }

  reset = (): void => {
    this.info = null;
    this.setState((state) => ({ error: null, resetKey: state.resetKey + 1 }));
  };

  render(): ReactNode {
    const { error, resetKey } = this.state;
    const { children, fallback, label, compact, className } = this.props;

    if (error) {
      let content: ReactNode;
      if (typeof fallback === 'function') {
        content = fallback({ error, reset: this.reset });
      } else if (fallback !== undefined) {
        content = fallback;
      } else {
        content = (
          <LoadFailedFallback error={error} info={this.info} label={label} compact={compact} reset={this.reset} />
        );
      }
      return className ? <div className={cn(className)}>{content}</div> : content;
    }

    // Keying the fragment by `resetKey` forces a full remount on retry.
    return <Fragment key={resetKey}>{children}</Fragment>;
  }
}

export default ErrorBoundary;
