import { useEffect, useState } from 'react';
import { SHORTCUTS, loadBindings } from '../services/shortcuts';
import { Dialog } from '../ui/Dialog';

export default function ShortcutHelpDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [bindings, setBindings] = useState(loadBindings);
  useEffect(() => {
    const refresh = () => setBindings(loadBindings());
    window.addEventListener('atlas:shortcuts', refresh);
    return () => window.removeEventListener('atlas:shortcuts', refresh);
  }, []);

  return <Dialog open={open} onOpenChange={onOpenChange} label="会话与应用快捷键"
    className="max-h-[82vh] w-[min(680px,92vw)] overflow-auto bg-panel p-4 shadow-xl">
    <div className="mb-2 flex items-center gap-2">
      <h2 className="m-0 text-[16px] font-semibold text-heading">会话与应用快捷键</h2>
      <span className="flex-1" />
      <button type="button" aria-label="关闭快捷键帮助" onClick={() => onOpenChange(false)}
        className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover hover:text-fg focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand">×</button>
    </div>
    <p className="mb-3 text-[12.5px] leading-relaxed text-fg-3">快捷键可在设置 → 快捷键中调整。输入区的编辑和建议列表按键可从消息输入框旁的帮助按钮查看。</p>
    <dl className="m-0 grid grid-cols-[minmax(180px,1fr)_minmax(130px,auto)] gap-x-4 text-[12.5px]">
      {SHORTCUTS.map(({ action, label, hint }) => {
        const combos = bindings[action] ?? [];
        return <div key={action} className="contents">
          <dt className="border-t border-line py-2 text-fg-2">{label}{hint && <span className="ml-2 text-fg-3">{hint}</span>}</dt>
          <dd className="m-0 border-t border-line py-2 text-right font-mono text-fg">
            {combos.length ? combos.join('　/　') : <span className="font-sans text-fg-3">未设置</span>}
          </dd>
        </div>;
      })}
    </dl>
    <p className="mb-0 mt-3 border-t border-line pt-3 text-[12px] text-fg-3">按 Escape 或点击外侧关闭。</p>
  </Dialog>;
}
