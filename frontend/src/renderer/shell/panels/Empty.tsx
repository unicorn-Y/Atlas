import type { ReactNode } from 'react';

export function Empty({ title, body, icon, action }: { title: string; body: string; icon?: ReactNode; action?: ReactNode }) {
  return <div className="px-2 py-10 text-center">
    {icon && <div className="mb-2 flex justify-center text-fg-3">{icon}</div>}
    <b className="block text-[14px] font-medium text-fg">{title}</b>
    <p className="m-0 mt-1 text-[13px] leading-[1.6] text-fg-3">{body}</p>
    {action && <div className="mt-4 flex justify-center">{action}</div>}
  </div>;
}
