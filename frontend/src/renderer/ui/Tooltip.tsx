import type { ReactElement, ReactNode } from 'react';
import * as T from '@radix-ui/react-tooltip';

export const TooltipProvider = ({ children }: { children: ReactNode }) =>
  <T.Provider delayDuration={400} skipDelayDuration={150}>{children}</T.Provider>;

/** Hover hint for icon-only controls. The child must accept a ref (a button). */
export function Tip({ label, side = 'bottom', children }: { label: ReactNode; side?: 'top' | 'bottom' | 'left' | 'right'; children: ReactElement }) {
  return <T.Root>
    <T.Trigger asChild>{children}</T.Trigger>
    <T.Portal>
      <T.Content side={side} sideOffset={6} className="pop anim-fade z-[70] rounded-lg px-2.5 py-1 text-[12px] text-fg">
        {label}
      </T.Content>
    </T.Portal>
  </T.Root>;
}
