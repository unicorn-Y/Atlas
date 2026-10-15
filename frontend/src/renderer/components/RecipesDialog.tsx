import { useEffect, useState, type FormEvent } from 'react';
import { BookMarked, Play, Trash2 } from 'lucide-react';
import type { Recipe } from '@atlas/backend-adapter';
import { Dialog } from '../ui/Dialog';
import { Button } from '../ui/Button';
import { cn } from '../ui/cn';

/** Saved tasks that can be run again with new parameters. */
export default function RecipesDialog({ open, onClose, recipes, onRun, onDelete }: {
  open: boolean;
  onClose: () => void;
  recipes: Recipe[];
  onRun: (id: string, params: Record<string, string>) => void;
  onDelete: (id: string) => void;
}) {
  const [selected, setSelected] = useState('');
  const [params, setParams] = useState<Record<string, string>>({});
  const [confirmDelete, setConfirmDelete] = useState(false);
  const current = recipes.find((recipe) => recipe.id === selected) ?? recipes[0];
  useEffect(() => {
    setConfirmDelete(false);
    setParams(Object.fromEntries((current?.params ?? []).map((param) => [param.name, param.default ?? ''])));
  }, [current?.id]);

  const run = (event: FormEvent) => {
    event.preventDefault();
    if (!current) return;
    onRun(current.id, params);
    onClose();
  };

  return <Dialog open={open} onOpenChange={(next) => { if (!next) onClose(); }} label="配方" className="grid h-[min(560px,calc(100vh-48px))] w-[min(820px,calc(100vw-32px))] grid-cols-[240px_minmax(0,1fr)]">
    <nav className="overflow-auto bg-sunken p-2.5 shadow-[inset_-1px_0_0_var(--line)]" aria-label="配方列表">
      <h2 className="m-0 px-2 pt-2 pb-3 text-[17px] font-semibold text-heading">配方</h2>
      {recipes.map((recipe) => <button key={recipe.id} onClick={() => setSelected(recipe.id)} aria-current={current?.id === recipe.id}
        className={cn('block w-full truncate rounded-lg px-2.5 py-2 text-left text-[13px]', current?.id === recipe.id ? 'bg-selected text-fg' : 'text-fg-2 hover:bg-hover hover:text-fg')}>{recipe.name}</button>)}
      {!recipes.length && <p className="m-0 px-2 text-[12.5px] leading-[1.6] text-fg-3">还没有配方。任务做完后点完成行上的「存为配方」，下次就能一键复跑。</p>}
    </nav>
    <div className="min-h-0 overflow-auto p-6">
      {current ? <form onSubmit={run} className="grid gap-4">
        <div>
          <h3 className="m-0 flex items-center gap-2 text-[16px] font-semibold text-heading"><BookMarked size={17} className="text-brand" />{current.name}</h3>
          {current.description && <p className="mt-1 mb-0 text-[13px] text-fg-3">{current.description}</p>}
        </div>
        <pre className="m-0 max-h-48 overflow-auto rounded-xl bg-code p-3 font-mono text-[12px] leading-[1.6] whitespace-pre-wrap text-fg-2">{current.prompt}</pre>
        {current.params.length > 0 && <div className="grid gap-3">
          {current.params.map((param) => <label key={param.name} className="grid gap-1 text-[13px] text-fg-2">{param.label || param.name}
            <input value={params[param.name] ?? ''} onChange={(event) => setParams({ ...params, [param.name]: event.target.value })}
              className="h-9 rounded-[9px] bg-sunken px-3 text-[13.5px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]" />
          </label>)}
        </div>}
        <p className="m-0 text-[12px] text-fg-3">{[current.mode === 'plan' && '先出计划', current.profile_id && `角色：${current.profile_id}`, current.active_skills?.length && `技能：${current.active_skills.join('、')}`, current.workspace && `目录：${current.workspace}`].filter(Boolean).join(' · ') || '按默认设置运行'}</p>
        <div className="flex gap-2">
          <Button type="submit" variant="primary"><Play />在当前对话运行</Button>
          <Button variant={confirmDelete ? 'danger' : 'ghost'} onClick={() => { if (confirmDelete) { onDelete(current.id); setConfirmDelete(false); } else setConfirmDelete(true); }}><Trash2 />{confirmDelete ? '确认删除' : '删除'}</Button>
        </div>
      </form> : <p className="text-[13px] text-fg-3">选一个配方。</p>}
    </div>
  </Dialog>;
}
