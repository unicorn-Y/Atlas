import { useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { Plus, RotateCcw, X } from 'lucide-react';
import {
  comboFromEvent,
  defaultBindings,
  findDuplicateBinding,
  findShortcutConflict,
  loadBindings,
  matchesShortcutKey,
  matchesShortcutSearch,
  sameBindings,
  saveBindings,
  SHORTCUTS,
  shortcutRejection,
  type ShortcutAction,
  type ShortcutBindings,
} from '../services/shortcuts';
import { Kbd } from '../ui/Kbd';
import { cn } from '../ui/cn';
import type { ModelInfo } from '@atlas/backend-adapter';

type RecordingTarget = { action: ShortcutAction; bindingIndex: number | null };

/** Manage app shortcuts: search, record one or more bindings, clear, or restore defaults. */
export default function ShortcutsPanel({ models = [] }: { models?: ModelInfo[] }) {
  const [bindings, setBindings] = useState<ShortcutBindings>(loadBindings);
  const [recording, setRecording] = useState<RecordingTarget | null>(null);
  const [query, setQuery] = useState('');
  const [keyFilter, setKeyFilter] = useState('');
  const [searchRecording, setSearchRecording] = useState(false);
  const [note, setNote] = useState('');
  const [showHints, setShowHints] = useState(() => { try { return localStorage.getItem('atlas.shortcut-hints') !== 'false'; } catch { return true; } });
  const [cycleModels, setCycleModels] = useState<string[]>(() => { try { const value: unknown = JSON.parse(localStorage.getItem('atlas.model-cycle') ?? '[]'); return Array.isArray(value) ? value.filter((id): id is string => typeof id === 'string') : []; } catch { return []; } });

  const update = (next: ShortcutBindings) => { setBindings(next); saveBindings(next); };
  const defaults = defaultBindings();
  const changed = SHORTCUTS.some(({ action }) => !sameBindings(bindings[action], defaults[action]));

  const restoreAction = (action: ShortcutAction) => {
    const combo = defaults[action][0];
    const conflict = combo && findShortcutConflict(action, combo, bindings);
    if (conflict) {
      const label = SHORTCUTS.find((item) => item.action === conflict)?.label ?? conflict;
      setNote(`${combo} 已分配给「${label}」，无法恢复此项默认快捷键`);
      return;
    }
    update({ ...bindings, [action]: defaults[action] });
    setNote('已恢复此项默认快捷键');
  };

  const record = (target: RecordingTarget, event: ReactKeyboardEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'Escape') { setRecording(null); setNote('已取消录入'); return; }

    const clear = (event.key === 'Backspace' || event.key === 'Delete')
      && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey;
    if (clear) {
      if (target.bindingIndex === null) {
        setNote('请在已有按键上按 Backspace 或 Delete 清除该绑定');
        return;
      }
      const next = [...bindings[target.action]];
      next.splice(target.bindingIndex, 1);
      update({ ...bindings, [target.action]: next });
      setRecording(null);
      setNote(next.length ? '已清除这组按键' : '已清除最后一组按键，这个操作现在没有快捷键');
      return;
    }

    const combo = comboFromEvent(event.nativeEvent);
    if (!combo) return;
    const current = bindings[target.action];
    const signature = combo.toUpperCase();
    if (target.bindingIndex !== null && current[target.bindingIndex]?.toUpperCase() === signature) {
      setRecording(null);
      setNote('');
      return;
    }
    if (findDuplicateBinding(target.action, combo, bindings)) {
      setNote(`「${SHORTCUTS.find((item) => item.action === target.action)?.label}」已经有 ${combo}`);
      return;
    }

    const conflict = findShortcutConflict(target.action, combo, bindings);
    if (conflict) {
      const label = SHORTCUTS.find((item) => item.action === conflict)?.label ?? conflict;
      setNote(`${combo} 已分配给「${label}」，请换一组按键`);
      return;
    }

    const rejection = shortcutRejection(combo);
    if (rejection) { setNote(rejection); return; }

    const next = [...current];
    if (target.bindingIndex === null) next.push(combo);
    else next[target.bindingIndex] = combo;
    update({ ...bindings, [target.action]: next });
    setRecording(null);
    setNote(`已设置 ${combo}`);
  };

  const recordSearchKey = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'Escape') { setSearchRecording(false); setNote('已取消按键搜索'); return; }
    if ((event.key === 'Backspace' || event.key === 'Delete')
      && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey) {
      setKeyFilter('');
      setSearchRecording(false);
      setNote('已清除按键搜索');
      return;
    }
    const combo = comboFromEvent(event.nativeEvent);
    if (!combo) return;
    setKeyFilter(combo);
    setSearchRecording(false);
    setNote(`正在按 ${combo} 筛选`);
  };

  const visibleShortcuts = SHORTCUTS.filter((item) => {
    const textMatches = [item.label, item.hint ?? '', item.action, ...bindings[item.action]]
      .some((value) => matchesShortcutSearch(value, query));
    const keyMatches = !keyFilter || bindings[item.action].some((combo) => matchesShortcutKey(combo, keyFilter));
    return textMatches && keyMatches;
  });

  return <div className="grid gap-1" data-shortcut-recorder>
    <div className="mb-3 grid gap-3 rounded-xl bg-sunken p-3">
      <label className="flex items-center gap-2 text-[12.5px] text-fg-2"><input type="checkbox" checked={showHints} onChange={(event) => { const enabled = event.target.checked; setShowHints(enabled); try { localStorage.setItem('atlas.shortcut-hints', String(enabled)); } catch { /* storage unavailable */ } window.dispatchEvent(new Event('atlas:shortcut-hints')); }} />在输入框下方显示按键提示</label>
      <div className="grid gap-1.5"><span className="text-[12.5px] font-medium text-fg-2">Ctrl+P 模型循环</span><p className="m-0 text-[11.5px] text-fg-3">勾选常用模型；未选时会循环所有已配置模型。</p>{models.map((model) => <label key={model.id} className="flex items-center gap-2 text-[12px] text-fg-2"><input type="checkbox" checked={cycleModels.includes(model.id)} onChange={(event) => { const next = event.target.checked ? [...cycleModels, model.id] : cycleModels.filter((id) => id !== model.id); setCycleModels(next); try { localStorage.setItem('atlas.model-cycle', JSON.stringify(next)); } catch { /* storage unavailable */ } }} />{model.name ?? model.id}</label>)}</div>
    </div>
    <div className="mb-2 grid gap-2 px-2">
      <input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="搜索操作或快捷键"
        aria-label="搜索操作或快捷键"
        className="h-9 rounded-lg border border-line bg-sheet px-3 text-[13px] text-fg outline-none placeholder:text-fg-3 focus:border-brand"
      />
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => { setSearchRecording((active) => !active); setRecording(null); setNote(''); }}
          onKeyDown={recordSearchKey}
          onBlur={() => { if (searchRecording) setSearchRecording(false); }}
          aria-label="按快捷键搜索"
          className={cn('h-7 rounded-md px-2 text-[12px]', searchRecording ? 'bg-brand-soft text-fg' : 'text-fg-3 hover:bg-hover hover:text-fg')}
        >{searchRecording ? '按下要搜索的组合键…' : '按键搜索'}</button>
        {keyFilter && <button type="button" onClick={() => { setKeyFilter(''); setNote(''); }} className="text-[12px] text-fg-3 hover:text-fg">
          清除 {keyFilter} <X size={12} className="inline" />
        </button>}
        <span className="flex-1 text-right text-[12px] text-fg-3">可按操作名称或组合键过滤</span>
      </div>
    </div>

    {visibleShortcuts.map((item) => {
      const combos = bindings[item.action];
      const isDefault = sameBindings(combos, defaults[item.action]);
      return <div key={item.action} className="flex flex-wrap items-center gap-3 rounded-lg px-2 py-2 hover:bg-hover">
        <div className="min-w-[180px] flex-1 text-[13.5px] text-fg">
          {item.label}{item.hint && <small className="ml-2 text-[12px] text-fg-3">{item.hint}</small>}
        </div>
        <div className="flex min-w-[160px] flex-wrap items-center justify-end gap-1">
          {combos.length === 0 && <span className="px-2 text-[12px] text-fg-3">未设置</span>}
          {combos.map((combo, index) => {
            const target = { action: item.action, bindingIndex: index };
            const active = recording?.action === item.action && recording.bindingIndex === index;
            return <span key={`${combo}-${index}`} className="flex items-center gap-0.5 rounded-md bg-surface px-1 shadow-[inset_0_0_0_1px_var(--line)]">
              <button
                type="button"
                onClick={() => { setRecording(active ? null : target); setSearchRecording(false); setNote(''); }}
                onKeyDown={(event) => { if (active) record(target, event); }}
                onBlur={() => { if (active) setRecording(null); }}
                aria-label={`修改「${item.label}」的第 ${index + 1} 组快捷键`}
                className={cn('flex h-7 items-center gap-1 rounded px-1.5 text-[12px]', active ? 'bg-brand-soft text-fg shadow-[inset_0_0_0_1px_var(--brand)]' : 'text-fg-3 hover:text-fg')}
              >
                {active ? '按下新组合键…' : combo.split('+').map((key, keyIndex) => <Kbd key={`${key}-${keyIndex}`}>{key}</Kbd>)}
              </button>
              <button
                type="button"
                title="清除这组快捷键"
                aria-label={`清除「${item.label}」的第 ${index + 1} 组快捷键`}
                onClick={() => {
                  const next = combos.filter((_, currentIndex) => currentIndex !== index);
                  update({ ...bindings, [item.action]: next });
                  setNote(next.length ? '已清除这组按键' : '已清除最后一组按键，这个操作现在没有快捷键');
                }}
                className="grid size-6 place-items-center rounded text-fg-3 hover:bg-hover hover:text-fg"
              ><X size={12} /></button>
            </span>;
          })}
          <button
            type="button"
            onClick={() => { setRecording(recording?.action === item.action && recording.bindingIndex === null ? null : { action: item.action, bindingIndex: null }); setSearchRecording(false); setNote(''); }}
            onKeyDown={(event) => { if (recording?.action === item.action && recording.bindingIndex === null) record({ action: item.action, bindingIndex: null }, event); }}
            onBlur={() => { if (recording?.action === item.action && recording.bindingIndex === null) setRecording(null); }}
            aria-label={`为「${item.label}」添加快捷键`}
            title="添加另一组快捷键"
            className={cn('grid h-7 min-w-7 place-items-center rounded-md px-1 text-fg-3 hover:bg-hover hover:text-fg', recording?.action === item.action && recording.bindingIndex === null && 'bg-brand-soft text-fg')}
          >{recording?.action === item.action && recording.bindingIndex === null ? '按键…' : <Plus size={14} />}</button>
        </div>
        <button
          type="button"
          title="恢复默认"
          aria-label={`恢复「${item.label}」的默认快捷键`}
          disabled={isDefault}
          onClick={() => restoreAction(item.action)}
          className="grid size-7 place-items-center rounded-md text-fg-3 hover:bg-hover hover:text-fg disabled:invisible"
        ><RotateCcw size={13} /></button>
      </div>;
    })}

    {visibleShortcuts.length === 0 && <div className="px-2 py-4 text-center text-[12.5px] text-fg-3">没有匹配的快捷键</div>}
    <div className="mt-2 flex items-center gap-3 text-[12.5px] text-fg-3">
      <span className="flex-1" role="status">{note || '点按键开始录入。Esc 取消，Backspace 或 Delete 清除当前绑定。'}</span>
      {changed && <button type="button" onClick={() => { update(defaults); setRecording(null); setSearchRecording(false); setNote('已全部恢复默认'); }} className="text-fg-2 hover:text-fg">全部恢复默认</button>}
    </div>
  </div>;
}
