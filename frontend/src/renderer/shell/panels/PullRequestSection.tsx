import { useEffect, useState, type FormEvent } from 'react';
import { CircleCheck, CircleDashed, CircleX, ExternalLink, GitPullRequest, LoaderCircle, MessageSquarePlus, Send, Wrench } from 'lucide-react';
import type { PullRequestInfo } from '@atlas/backend-adapter';
import { api, relativeTime } from '../../services/api';
import { backend, useAtlasStore } from '../../store/useAtlasStore';
import { cn } from '../../ui/cn';

const failed = (conclusion: string | null) => ['FAILURE', 'failure', 'TIMED_OUT', 'CANCELLED', 'ACTION_REQUIRED'].includes(String(conclusion));
interface PullRequestActivity { id: string; kind: string; author: string; body: string; created_at: string; url?: string | null }
interface PullRequestTimeline { items: PullRequestActivity[] }

/** The branch's pull request and its checks, via the gh CLI; failed checks can go straight to Atlas. */
export default function PullRequestSection({ root, refreshKey, onOpenUrl, onAsk }: {
  root: string; refreshKey: string; onOpenUrl: (url: string) => void; onAsk: (text: string) => void;
}) {
  const [pr, setPr] = useState<PullRequestInfo | null | undefined>(undefined);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ title: '', body: '', draft: false });
  const [busy, setBusy] = useState('');
  const [timeline, setTimeline] = useState<PullRequestActivity[] | null | undefined>(undefined);
  const [timelineError, setTimelineError] = useState('');
  const [comment, setComment] = useState('');
  const [autoMerge, setAutoMerge] = useState(false);
  const [mergeMethod, setMergeMethod] = useState<'squash' | 'merge' | 'rebase'>('squash');
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);

  useEffect(() => {
    let stale = false;
    setPr(undefined); setError(''); setTimeline(undefined); setTimelineError('');
    backend.getPullRequest(root).then(async (result) => {
      if (stale) return;
      setPr(result);
      setAutoMerge(Boolean((result as (PullRequestInfo & { auto_merge?: boolean }) | null)?.auto_merge));
      const method = (result as (PullRequestInfo & { auto_merge_method?: string }) | null)?.auto_merge_method;
      if (method === 'MERGE' || method === 'REBASE' || method === 'SQUASH') setMergeMethod(method.toLowerCase() as 'squash' | 'merge' | 'rebase');
      if (!result) { setTimeline([]); return; }
      try {
        const data = await api<PullRequestTimeline>(apiBaseUrl, `/api/git/pr/timeline?root=${encodeURIComponent(root)}`);
        if (!stale) setTimeline(Array.isArray(data.items) ? data.items : []);
      } catch (exc) {
        if (!stale) { setTimeline(null); setTimelineError(exc instanceof Error ? exc.message : String(exc)); }
      }
    }).catch((exc) => { if (!stale) { setPr(null); setError(exc instanceof Error ? exc.message : String(exc)); } });
    return () => { stale = true; };
  }, [apiBaseUrl, root, refreshKey]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy('create'); setError('');
    try {
      setPr(await backend.createPullRequest(root, form.title.trim(), form.body, form.draft)); setCreating(false);
      try {
        const data = await api<PullRequestTimeline>(apiBaseUrl, `/api/git/pr/timeline?root=${encodeURIComponent(root)}`);
        setTimeline(Array.isArray(data.items) ? data.items : []);
        setTimelineError('');
      } catch (exc) { setTimeline(null); setTimelineError(exc instanceof Error ? exc.message : String(exc)); }
    }
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
  const submitComment = async (event: FormEvent) => {
    event.preventDefault();
    const body = comment.trim();
    if (!body || busy) return;
    setBusy('comment'); setTimelineError('');
    try {
      await api(apiBaseUrl, '/api/git/pr/comment', { method: 'POST', json: { root, body } });
      setComment('');
      const data = await api<PullRequestTimeline>(apiBaseUrl, `/api/git/pr/timeline?root=${encodeURIComponent(root)}`);
      setTimeline(Array.isArray(data.items) ? data.items : []);
    } catch (exc) { setTimelineError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };
  const toggleAutoMerge = async (enabled: boolean) => {
    setBusy('auto-merge'); setError('');
    try {
      const result = await api<{ enabled: boolean; auto_merge?: { mergeMethod?: string } | null }>(apiBaseUrl, '/api/git/pr/auto-merge', { method: 'POST', json: { root, enabled, method: mergeMethod } });
      setAutoMerge(result.enabled);
    } catch (exc) { setError(exc instanceof Error ? exc.message : String(exc)); }
    finally { setBusy(''); }
  };

  const field = 'rounded-[9px] bg-sunken px-3 text-[13px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  return <section>
    <h3 className="m-0 mb-2 flex items-center gap-1.5 text-[12.5px] font-semibold text-fg-2"><GitPullRequest size={13} />拉取请求（PR）</h3>
    {pr === undefined && !error && <p className="m-0 text-[12.5px] text-fg-3">正在查…</p>}
    {error && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-3 py-2 text-[12px] text-danger">{/gh|auth|login/i.test(error) ? `需要先安装并登录 GitHub CLI（gh auth login）。${error}` : error}</p>}
    {pr && <div className="rounded-xl bg-sunken px-3 py-2.5 text-[12.5px]">
      <button type="button" aria-label={`在浏览器打开 PR #${pr.number}：${pr.title}`} onClick={() => onOpenUrl(pr.url)} className="block w-full truncate text-left font-medium text-fg hover:underline">#{pr.number} {pr.title}</button>
      <p className="m-0 mt-0.5 text-fg-3">{pr.draft ? '草稿 · ' : ''}{pr.state} · {pr.head} → {pr.base}</p>
      <button type="button" onClick={() => onOpenUrl(pr.url)} className="mt-1 inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-[11.5px] text-fg-2 hover:bg-hover hover:text-fg">
        <ExternalLink size={11} />在浏览器查看 PR
      </button>
      <div className="mt-2 flex items-center gap-2 text-[11.5px] text-fg-2"><label className="flex items-center gap-2"><input type="checkbox" checked={autoMerge} disabled={Boolean(busy)} onChange={(event) => void toggleAutoMerge(event.target.checked)} />自动合并</label><select aria-label="自动合并方式" value={mergeMethod} disabled={Boolean(busy)} onChange={(event) => setMergeMethod(event.target.value as 'squash' | 'merge' | 'rebase')} className="rounded-md border border-line bg-surface px-1.5 py-1"><option value="squash">squash</option><option value="merge">merge</option><option value="rebase">rebase</option></select><span>· {autoMerge ? '已从 GitHub 读取开启状态' : '关闭'}</span></div>
      {pr.checks.length > 0 && <ul className="m-0 mt-2 grid list-none gap-1 p-0">
        {pr.checks.map((check) => <li key={check.name} className="flex items-center gap-1.5">
          {failed(check.conclusion) ? <CircleX size={13} className="shrink-0 text-danger" /> : check.conclusion ? <CircleCheck size={13} className="shrink-0 text-ok" /> : <CircleDashed size={13} className="shrink-0 text-fg-3" />}
          {check.url
            ? <button type="button" aria-label={`打开检查 ${check.name}：${check.conclusion ?? check.status}`} onClick={() => onOpenUrl(check.url!)} className={cn('min-w-0 flex-1 truncate text-left hover:underline', failed(check.conclusion) ? 'text-danger' : 'text-fg-2')}>{check.name}<span className="ml-1 text-fg-3">{check.conclusion ?? check.status}</span></button>
            : <span className={cn('min-w-0 flex-1 truncate', failed(check.conclusion) ? 'text-danger' : 'text-fg-2')}>{check.name}<span className="ml-1 text-fg-3">{check.conclusion ?? check.status}</span></span>}
          {failed(check.conclusion) && <button disabled={Boolean(busy)} onClick={() => void fix(check.name)} className="inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-fg-2 hover:bg-hover hover:text-fg disabled:opacity-50">
            {busy === check.name ? <LoaderCircle size={12} className="spin" /> : <Wrench size={12} />}让 Atlas 修</button>}
        </li>)}
      </ul>}
      <div className="mt-3 border-t border-line pt-2.5">
        <h4 className="m-0 mb-2 flex items-center gap-1.5 text-[11.5px] font-semibold text-fg-2"><MessageSquarePlus size={12} />PR 活动与评论</h4>
        {timelineError && <p role="alert" className="m-0 mb-2 rounded-lg bg-danger-soft px-2.5 py-2 text-[11.5px] text-danger">{timelineError}</p>}
        {timeline === undefined && <p className="m-0 text-[11.5px] text-fg-3">正在加载 PR 活动…</p>}
        {timeline && timeline.length === 0 && <p className="m-0 text-[11.5px] text-fg-3">暂无可显示的 PR 活动。</p>}
        {timeline && timeline.length > 0 && <ol className="m-0 grid list-none gap-2 p-0">
          {timeline.map((item) => <li key={item.id} className="rounded-lg bg-surface px-2.5 py-2 text-[11.5px]">
            <div className="flex items-start justify-between gap-2 text-fg-3">
              <span className="min-w-0 truncate text-fg-2">{item.author} · {item.kind}</span>
              <span className="shrink-0">{relativeTime(item.created_at)}</span>
            </div>
            {item.body && <p className="mb-0 mt-1 whitespace-pre-wrap break-words text-fg-2">{item.body}</p>}
            {item.body && /comment|review/i.test(item.kind) && <button type="button" onClick={() => onAsk(`请处理这条 PR ${item.kind} 意见。先结合仓库现状判断是否适用；如需修改请完成并验证，最后说明处理结果。\n\n作者：${item.author}\n\n${item.body}`)} className="mt-1 rounded-md px-1.5 py-1 text-[11px] text-brand hover:bg-hover">带入当前对话</button>}
            {item.url && <button type="button" onClick={() => onOpenUrl(item.url!)} className="mt-1 inline-flex items-center gap-1 text-fg-3 hover:text-fg"><ExternalLink size={10} />打开活动</button>}
          </li>)}
        </ol>}
        <form onSubmit={(event) => void submitComment(event)} className="mt-2 grid gap-1.5">
          <textarea value={comment} onChange={(event) => setComment(event.target.value)} rows={3} placeholder="添加 PR 评论…" aria-label="PR 评论" className={cn(field, 'py-2')} />
          <button disabled={busy === 'comment' || !comment.trim()} className="primary-fill inline-flex h-7 w-fit items-center gap-1 rounded-lg px-2.5 text-[11.5px] disabled:opacity-50">
            {busy === 'comment' ? <LoaderCircle size={11} className="spin" /> : <Send size={11} />}提交评论
          </button>
        </form>
      </div>
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
