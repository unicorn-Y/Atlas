import { X } from 'lucide-react';
import { SHORTCUTS, loadBindings } from '../services/shortcuts';

/** Compact shortcut reference; the editable bindings remain in the existing Settings panel. */
export default function KeymapDialog({ onClose }: { onClose: () => void }) {
  const bindings = loadBindings();
  const groups = new Map<string, typeof SHORTCUTS>();
  for (const item of SHORTCUTS) {
    const group = item.action.startsWith('sidebar') ? '侧栏' : ['palette', 'newTask', 'focusComposer'].includes(item.action) ? '对话' : '窗口';
    groups.set(group, [...(groups.get(group) ?? []), item]);
  }
  return <div className="fixed inset-0 z-[140] grid place-items-center bg-black/35 p-4" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <section role="dialog" aria-modal="true" aria-labelledby="keymap-title" className="w-full max-w-[620px] rounded-2xl border border-line bg-panel p-5 shadow-2xl">
      <header className="mb-4 flex items-center gap-2"><h2 id="keymap-title" className="m-0 flex-1 text-[16px] font-semibold text-heading">快捷键一览</h2><button aria-label="关闭快捷键一览" onClick={onClose} className="grid size-8 place-items-center rounded-lg text-fg-3 hover:bg-hover"><X size={16}/></button></header>
      <div className="grid max-h-[65vh] gap-4 overflow-auto sm:grid-cols-2">
        {[...groups].map(([group, entries]) => <section key={group}><h3 className="mb-2 text-[12px] font-semibold text-fg-3">{group}</h3><div className="grid gap-1">{entries.map((item) => <div key={item.action} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-[12.5px] hover:bg-hover"><span className="flex-1 text-fg-2">{item.label}</span><span className="text-right font-mono text-[11px] text-fg-3">{bindings[item.action].join(' / ') || '未绑定'}</span></div>)}</div></section>)}
      </div>
      <p className="mb-0 mt-4 text-[11.5px] text-fg-3">按 ? 或输入 /keymap 随时查看；在设置 → 快捷键中可录入和更改绑定。</p>
    </section>
  </div>;
}
