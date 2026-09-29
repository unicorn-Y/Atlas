import type { ReactNode } from 'react';
import * as D from '@radix-ui/react-dialog';
import { cn } from './cn';

/** Modal surface with a dimmed backdrop. Escape and backdrop clicks close it. */
export function Dialog({ open, onOpenChange, label, children, className, align = 'center' }: {
  open: boolean; onOpenChange: (open: boolean) => void; label: string; children: ReactNode; className?: string; align?: 'center' | 'top';
}) {
  return <D.Root open={open} onOpenChange={onOpenChange}>
    <D.Portal>
      <D.Overlay className="anim-fade fixed inset-0 z-50 bg-black/35 backdrop-blur-[2px] dark:bg-black/55" />
      <D.Content aria-describedby={undefined}
        className={cn('pop anim-pop fixed left-1/2 z-50 -translate-x-1/2 overflow-hidden rounded-2xl outline-none',
          align === 'center' ? 'top-1/2 -translate-y-1/2' : 'top-[14vh]', className)}>
        <D.Title className="sr-only">{label}</D.Title>
        {children}
      </D.Content>
    </D.Portal>
  </D.Root>;
}
