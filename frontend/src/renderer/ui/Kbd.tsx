import type { ReactNode } from 'react';
import { cn } from './cn';

export function Kbd({ children, className }: { children: ReactNode; className?: string }) {
  return <kbd className={cn('inline-flex h-5 items-center rounded-md px-1.5 font-sans text-[11px] text-fg-3 shadow-[inset_0_0_0_1px_var(--line-strong)]', className)}>{children}</kbd>;
}
