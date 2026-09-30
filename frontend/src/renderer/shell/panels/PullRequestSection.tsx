import { useEffect, useState, type FormEvent } from 'react';
import { CircleCheck, CircleDashed, CircleX, GitPullRequest, LoaderCircle, Wrench } from 'lucide-react';
import type { PullRequestInfo } from '@atlas/backend-adapter';
import { backend } from '../../store/useAtlasStore';
import { cn } from '../../ui/cn';

const failed = (conclusion: string | null) => ['FAILURE', 'failure', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED'].includes(String(conclusion));

/** The branch's pull request and its checks, via the gh CLI; failed checks can go straight to Atlas. */
export default function PullRequestSection({ root, refreshKey, onOpenUrl, onAsk }: {
  root: string; refreshKey: string; onOpenUrl: (url: string) => void; onAsk: (text: string) => void;
}) {
  const [pr, setPr] = useState<PullRequestInfo | null | undefined>(undefined);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: '', body: '', draft: false });
  const [busy, setBusy] = useState('');

  useEffect(() => {
    let stale = false;
    setPr(undefined); setError('');
    backend.getPullRequest(root).then((result) => { if (!stale) setPr(result); })
      .catch((exc) => { if (!stale) { setPr(null); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [root, refreshKey]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy('create'); setError('');
    try { setPr(await backend.createPullRequest(root, form.title.trim(), form.body, form.draft)); setCreating(false); }
    catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };
  const fix = async (name: string) => {
    setBusy(name); setError('');
    try {
      const log = await backend.getCheckLog(root, name);
      onAsk(`CI 检查「${name}」失败了。下面是日志末尾，找出原因并修好，修完说明改了什么：\n\n\`\`\`\n${log.trim().slice(-12000)}\n\`\`\``);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const field = 'rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <section>
    <h3 className="m-0 mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-fg-2"><GitPullRequest size={13} />拉取请求（PR）</h3>
    {pr === undefined && !error && <p className="m-0 text-[12.5px] text-fg-3">正在查…</p>}
    {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{/gh|auth|login/i.test(error) ? `需要先安装并登录 GitHub CLI（gh auth login）。${error}` : error}</p>}
    {pr && <div className="rounded-xl bg-sunken px-3 py-2.5 text-[12.5px]">
      <button onClick={() => onOpenUrl(pr.url)} className="block w-full truncate text-left font-medium text-fg hover:underline">#{pr.number} {pr.title}</button>
      <p className="m-0 mt-0.5 text-fg-3">{pr.draft ? '草稿 · ' : ''}{pr.state} · {pr.head} → {pr.base}</p>
      {pr.checks.length > 0 && <ul className="m-0 mt-2 grid list-none gap-1 p-0">
        {pr.checks.map((check) => <li key={check.name} className="flex items-center gap-1.5">
          {failed(check.conclusion) ? <CircleX size={13} className="shrink-0 text-danger" /> : check.conclusion ? <CircleCheck size={13} className="shrink-0 text-ok" /> : <CircleDashed size={13} className="shrink-0 text-fg-3" />}
          <span className={cn('min-w-0 flex-1 truncate', failed(check.conclusion) ? 'text-danger' : 'text-fg-2')}>{check.name}</span>
          {failed(check.conclusion) && <button disabled={Boolean(busy)} onClick={() => void fix(check.name)} className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50">
            {busy === check.name ? <LoaderCircle size={12} className="spin" /> : <Wrench size={12} />}让 Atlas 修</button>}
        </li>)}
      </ul>}
    </div>}
    {pr === null && !error && !creating && <button onClick={() => setCreating(true)} className="rounded-lg px-2 py-1 text-[12.5px] text-fg-2 hover:bg-hover hover:text-fg">这个分支还没有 PR，创建一个</button>}
    {creating && <form onSubmit={(event) => void create(event)} className="grid gap-2">
      <input autoFocus required value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} placeholder="PR 标题" aria-label="PR 标题" className={cn(field, 'h-8')} />
      <textarea value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} rows={3} placeholder="说明（可选）" aria-label="PR 说明" className={cn(field, 'py-2')} />
      <label className="flex items-center gap-2 text-[12.5px] text-fg-2"><input type="checkbox" checked={form.draft} onChange={(event) => setForm({ ...form, draft: event.target.checked })} />先建成草稿</label>
      <div className="flex gap-2">
        <button disabled={busy === 'create' || !form.title.trim()} className="primary-fill inline-flex h-7 items-center gap-1 rounded-lg px-2.5 text-[12.5px] disabled:opacity-50">{busy === 'create' && <LoaderCircle size={12} className="spin" />}推送并创建</button>
        <button type="button" onClick={() => setCreating(false)} className="rounded-lg px-2 text-[12.5px] text-fg-3 hover:text-fg">取消</button>
      </div>
    </form>}
  </section>;
}
