import { useState } from 'react';
import { RotateCcw } from 'lucide-react';
import { comboFromEvent, loadBindings, saveBindings, SHORTCUTS, type ShortcutAction } from '../services/shortcuts';
import { Kbd } from '../ui/Kbd';
import { cn } from '../ui/cn';

/** Rebind the app's shortcuts: click one, press the new keys (Esc cancels, Backspace clears). */
export default function ShortcutsPanel() {
  const [bindings, setBindings] = useState(loadBindings);
  const [recording, setRecording] = useState<ShortcutAction | null>(null);
  const [note, setNote] = useState('');

  const update = (next: Record<ShortcutAction, string>) => { setBindings(next); saveBindings(next); };
  const record = (action: ShortcutAction, event: React.KeyboardEvent) => {
    event.preventDefault(); event.stopPropagation();
    if (event.key === 'Escape') { setRecording(null); return; }
    if (event.key === 'Backspace' && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) {
      update({ ...bindings, [action]: '' }); setRecording(null); setNote('已清除，这个操作现在没有快捷键'); return;
    }
    const combo = comboFromEvent(event.nativeEvent);
    if (!combo) return;
    if (!/^(Ctrl|Alt)\+/.test(combo) && !/^F\d+$/.test(combo)) { setNote('需要带 Ctrl 或 Alt，免得和打字冲突'); return; }
    const clash = SHORTCUTS.find((item) => item.action !== action && bindings[item.action]?.toUpperCase() === combo.toUpperCase());
    const next = { ...bindings, [action]: combo };
    if (clash) next[clash.action] = '';
    update(next); setRecording(null);
    setNote(clash ? `「${clash.label}」原来也用 ${combo}，已把它清空` : '');
  };

  const defaults = Object.fromEntries(SHORTCUTS.map((item) => [item.action, item.combo])) as Record<ShortcutAction, string>;
  const changed = SHORTCUTS.some((item) => bindings[item.action] !== item.combo);
  return <div className="grid gap-1" data-shortcut-recorder>
    {SHORTCUTS.map((item) => {
      const active = recording === item.action;
      const combo = bindings[item.action];
      return <div key={item.action} className="flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-hover">
        <div className="min-w-0 flex-1 text-[13.5px] text-fg">{item.label}{item.hint && <small className="ml-2 text-[12px] text-fg-3">{item.hint}</small>}</div>
        <button onClick={() => { setRecording(active ? null : item.action); setNote(''); }} onKeyDown={(event) => { if (active) record(item.action, event); }}
          onBlur={() => { if (active) setRecording(null); }} aria-label={`${item.label}的快捷键`}
          className={cn('flex h-8 min-w-[132px] items-center justify-end gap-1 rounded-lg px-2 text-[12.5px]', active ? 'bg-brand-soft text-fg shadow-[inset_0_0_0_1px_var(--brand)]' : 'text-fg-3 hover:text-fg')}>
          {active ? '按下新的组合键…' : combo ? combo.split('+').map((key) => <Kbd key={key}>{key}</Kbd>) : '未设置'}
        </button>
        <button title="恢复默认" aria-label={`恢复「${item.label}」的默认快捷键`} disabled={combo === defaults[item.action]}
          onClick={() => update({ ...bindings, [item.action]: defaults[item.action] })}
          className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg disabled:invisible"><RotateCcw size={13} /></button>
      </div>;
    })}
    <div className="mt-2 flex items-center gap-3 text-[12.5px] text-fg-3">
      <span className="flex-1" role="status">{note || '点一下右边的按键，再按新的组合键。Esc 取消，Backspace 清除。'}</span>
      {changed && <button onClick={() => { update(defaults); setNote('已全部恢复默认'); }} className="text-fg-2 hover:text-fg">全部恢复默认</button>}
    </div>
  </div>;
}
