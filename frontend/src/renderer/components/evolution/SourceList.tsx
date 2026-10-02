import { useState, type FormEvent } from 'react';
import { LoaderCircle, Plus, RadioTower, Trash2 } from 'lucide-react';
import { EVOLUTION_KIND_LABEL, type EvolutionSource, type EvolutionSourceKind } from '../../services/evolutionApi';

const KIND_OPTIONS: EvolutionSourceKind[] = ['commit', 'tag', 'release'];

/** 上游监视来源：owner/name 仓库清单，可添加（commit/tag/release）与两段式删除。 */
export default function SourceList({ sources, busy, onAdd, onRemove }: {
  sources: EvolutionSource[];
  busy: boolean;
  onAdd: (source: { repo: string; kind: EvolutionSourceKind }) => void;
  onRemove: (id: string) => void;
}) {
  const [adding, setAdding] = useState(false);
  const [repo, setRepo] = useState('');
  const [kind, setKind] = useState<EvolutionSourceKind>('commit');
  const [armed, setArmed] = useState('');
  const [formError, setFormError] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = repo.trim();
    if (!/^[\w.-]+\/[\w.-]+$/.test(trimmed)) {
      setFormError('仓库格式应为 owner/name，例如 openai/codex');
      return;
    }
    setFormError('');
    onAdd({ repo: trimmed, kind });
    setRepo('');
    setAdding(false);
  };

  return <div>
    <ul className="m-0 list-none p-0">
      {sources.map((source) => <li key={source.id} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-hover">
        <span className="rounded-md bg-sunken px-1.5 py-0.5 text-[11.5px] text-fg-2">
          {EVOLUTION_KIND_LABEL[source.kind as EvolutionSourceKind] ?? source.kind}
        </span>
        <span className="min-w-0 flex-1 truncate text-[12.5px] text-fg-2">
          <span className="text-fg">{source.repo}</span>
          {source.ref && source.ref !== 'main' ? ` · ${source.ref}` : ''}
          {source.last_checked ? ` · 上次检查 ${source.last_checked.replace('T', ' ')}` : ' · 还没检查过'}
          {` · 缓存 ${source.cached_entries} 条`}
        </span>
        <button type="button" aria-label={`删除来源 ${source.repo}`}
          className={`btn ghost h-7 px-2 text-[12px] ${armed === source.id ? 'text-danger' : 'opacity-60 hover:opacity-100'}`}
          disabled={busy}
          onClick={() => { if (armed === source.id) { onRemove(source.id); setArmed(''); } else setArmed(source.id); }}>
          {armed === source.id ? <><Trash2 size={13} />再点一次删除</> : <><Trash2 size={13} />删除</>}
        </button>
      </li>)}
      {!sources.length && <li className="px-2 py-1.5 text-[12.5px] text-fg-3">
        还没有监视来源。添加上游仓库（owner/name）后，点「立即检查」拉取它的新动态。
      </li>}
    </ul>
    {formError && <div role="alert" className="error-note"><span>{formError}</span></div>}
    {adding ? <form className="form mt-3" onSubmit={submit}>
      <div className="two">
        <label>仓库（owner/name）<input aria-label="上游仓库" value={repo} onChange={(event) => setRepo(event.target.value)}
          placeholder="例如 anthropics/claude-code" /></label>
        <label>关注方式<select aria-label="关注方式" value={kind} onChange={(event) => setKind(event.target.value as EvolutionSourceKind)}>
          {KIND_OPTIONS.map((item) => <option key={item} value={item}>{EVOLUTION_KIND_LABEL[item]}</option>)}
        </select></label>
      </div>
      <div className="foot">
        <button type="button" className="btn ghost" disabled={busy} onClick={() => setAdding(false)}>取消</button>
        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <Plus size={15} />}{busy ? '正在添加…' : '添加来源'}
        </button>
      </div>
    </form> : <div className="mt-3">
      <button type="button" className="btn" disabled={busy} onClick={() => setAdding(true)}>
        <RadioTower size={15} />添加上游来源
      </button>
    </div>}
  </div>;
}
