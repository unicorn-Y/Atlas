import type { ReactNode } from 'react';
import * as M from '@radix-ui/react-dropdown-menu';
import { Check, ChevronRight } from 'lucide-react';
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

export function MenuItem({ children, onSelect, checked, hint, disabled }: { children: ReactNode; onSelect?: (event: Event) => void; checked?: boolean; hint?: ReactNode; disabled?: boolean }) {
  return <M.Item onSelect={onSelect} disabled={disabled}
    className="flex cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-fg outline-none data-[highlighted]:bg-hover data-[disabled]:cursor-default data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-fg-2">
    {children}
    {checked ? <Check className="ml-auto !text-brand" /> : hint ? <span className="ml-auto pl-3 text-[12px] text-fg-3">{hint}</span> : null}
  </M.Item>;
}

export const MenuSeparator = () => <M.Separator className="mx-1 my-1.5 h-px bg-line" />;

/** A row that opens a second-level menu: keeps long menus short by folding each group away. */
export function MenuSub({ label, value, icon, children, disabled }: { label: ReactNode; value?: ReactNode; icon?: ReactNode; children: ReactNode; disabled?: boolean }) {
  return <M.Sub>
    <M.SubTrigger disabled={disabled}
      className="flex cursor-pointer select-none items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13.5px] text-fg outline-none data-[highlighted]:bg-hover data-[state=open]:bg-hover data-[disabled]:opacity-50 [&_svg]:size-4 [&_svg]:text-fg-2">
      {icon}<span className="shrink-0">{label}</span>
      {value && <span className="ml-auto min-w-0 truncate pl-3 text-[12px] text-fg-3">{value}</span>}
      <ChevronRight className={cn('shrink-0 !size-3.5 !text-fg-3', !value && 'ml-auto')} />
    </M.SubTrigger>
    <M.Portal>
      <M.SubContent sideOffset={6} alignOffset={-6} className="pop anim-pop z-[61] max-h-[min(460px,75vh)] w-[320px] overflow-auto rounded-xl p-1.5">{children}</M.SubContent>
    </M.Portal>
  </M.Sub>;
}
