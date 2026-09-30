import type { ReactNode } from 'react';
import * as M from '@radix-ui/react-dropdown-menu';
import { Check } from 'lucide-react';
import { cn } from './cn';

export const Menu = M.Root;
export const MenuTrigger = M.Trigger;

export function MenuContent({ children, align = 'start', side = 'bottom', className }: { children: ReactNode; align?: 'start' | 'end' | 'center'; side?: 'top' | 'bottom'; className?: string }) {
  return <M.Portal>
    <M.Content align={align} side={side} sideOffset={6} className={cn('pop anim-pop z-[60] min-w-[220px] max-h-[360px] overflow-auto rounded-xl p-1.5', className)}>
      {children}
    </M.Content>
  </M.Portal>;
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <M.Label className="px-2.5 pt-1.5 pb-1 text-[12px] text-fg-3">{children}</M.Label>;
}

export function MenuItem({ children, onSelect, checked, hint }: { children: ReactNode; onSelect?: (event: Event) => void; checked?: boolean; hint?: ReactNode }) {
  return <M.Item onSelect={onSelect}
    className="flex cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-fg outline-none data-[highlighted]:bg-hover [&_svg]:size-4 [&_svg]:text-fg-2">
    {children}
    {checked ? <Check className="ml-auto !text-brand" /> : hint ? <span className="ml-auto pl-3 text-[12px] text-fg-3">{hint}</span> : null}
  </M.Item>;
}

export const MenuSeparator = () => <M.Separator className="mx-1 my-1.5 h-px bg-line" />;
