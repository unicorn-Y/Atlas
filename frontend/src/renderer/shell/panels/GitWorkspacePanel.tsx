import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { GitBranch, GitCommitHorizontal, GitPullRequest, LoaderCircle, RefreshCw, Upload } from 'lucide-react';
import { useAtlasStore } from '../../store/useAtlasStore';
import { api } from '../../services/api';

interface GitStatusEntry { path: string; code: string }
interface GitWorkspace { current: string | null; branches: string[]; status: GitStatusEntry[] }
interface GitCommit { hash: string; parents: string[]; subject: string; author: string; date: string }
interface GitHistory { graph: string[]; commits: GitCommit[] }

/** Branch controls, selected-path commit/push actions, and the repository's real commit graph. */
export default function GitWorkspacePanel({ root, conversationId, refreshKey, onChanged, onToast }: { root: string; conversationId?: string; refreshKey?: string; onChanged?: () => void; onToast?: (text: string) => void }) {
  const apiBaseUrl = useAtlasStore((state) => state.apiBaseUrl);
  const [workspace, setWorkspace] = useState<GitWorkspace | null>(null);
  const [history, setHistory] = useState<GitHistory | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [branchName, setBranchName] = useState('');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    if (!root || !apiBaseUrl) return;
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ root });
      const [nextWorkspace, nextHistory] = await Promise.all([
        api<GitWorkspace>(apiBaseUrl, `/api/git/workspace?${params}`),
        api<GitHistory>(apiBaseUrl, `/api/git/history?${new URLSearchParams({ root, limit: '200' })}`),
      ]);
      setWorkspace(nextWorkspace);
      setHistory(nextHistory);
      setSelected((current) => current.filter((path) => nextWorkspace.status.some((item) => item.path === path)));
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, root]);

  useEffect(() => {
    setWorkspace(null);
    setHistory(null);
    setSelected([]);
    setNotice('');
    void load();
  }, [load, refreshKey]);

  const paths = useMemo(() => workspace?.status.map((item) => item.path) ?? [], [workspace]);
  const allSelected = paths.length > 0 && paths.every((path) => selected.includes(path));
  const selectedLabel = `${selected.length} 个文件`;

  const runBranch = async (name: string, create: boolean) => {
    const value = name.trim();
    if (!value || busy) return;
    setBusy(create ? 'create-branch' : 'switch-branch');
    setError(''); setNotice('');
    try {
      const next = await api<GitWorkspace>(apiBaseUrl, '/api/git/branch', { method: 'POST', json: { root, name: value, create, ...(conversationId ? { conversation_id: conversationId } : {}) } });
      setWorkspace(next);
      setSelected((current) => current.filter((path) => next.status.some((item) => item.path === path)));
      setNotice(create ? `已新建并切换到 ${next.current ?? value}` : `已切换到 ${next.current ?? value}`);
      onToast?.(create ? `已切换到新分支 ${next.current ?? value}` : `已切换到分支 ${next.current ?? value}`);
      onChanged?.();
      setBranchName('');
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const commit = async (event?: FormEvent, pushAfter = false) => {
    event?.preventDefault();
    if (!message.trim() || !selected.length || busy) return;
    setBusy('commit'); setError(''); setNotice('');
    try {
      const result = await api<{ commit: string }>(apiBaseUrl, '/api/git/commit', { method: 'POST', json: { root, message: message.trim(), paths: selected } });
      setMessage('');
      if (pushAfter) {
        setBusy('push');
        try {
          const pushed = await api<{ pushed: string | number | boolean }>(apiBaseUrl, '/api/git/push', { method: 'POST', json: { root } });
          setNotice(`已提交 ${result.commit} 并推送${typeof pushed.pushed === 'string' ? `：${pushed.pushed}` : ''}`);
          onToast?.('提交并推送完成');
        } catch (exc) {
          await load();
          setError(`提交 ${result.commit} 已成功，但推送失败：${exc instanceof Error ? exc.message : String(exc)}`);
          return;
        }
      } else {
        setNotice(`已提交 ${result.commit}`);
        onToast?.(`已提交 ${result.commit}`);
      }
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const push = async () => {
    if (busy) return;
    setBusy('push'); setError(''); setNotice('');
    try {
      const result = await api<{ pushed: string | number | boolean }>(apiBaseUrl, '/api/git/push', { method: 'POST', json: { root } });
      setNotice(typeof result.pushed === 'string' ? `已推送：${result.pushed}` : '推送完成');
      onToast?.('推送完成');
      await load();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const field = 'h-8 min-w-0 rounded-[9px] bg-sunken px-2.5 text-[12px] text-fg outline-none shadow-[inset_0_0_0_1px_var(--line)] focus:shadow-[inset_0_0_0_1px_var(--brand)]';
  const action = 'inline-flex h-7 items-center justify-center gap-1 rounded-lg bg-hover px-2.5 text-[11.5px] font-medium text-fg-2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-45';

  return <section className="grid gap-3">
    <div className="flex items-center justify-between gap-2">
      <h3 className="m-0 flex items-center gap-1.5 text-[12.5px] font-semibold text-fg-2"><GitBranch size={13} />Git 工作区</h3>
      <button type="button" aria-label="刷新 Git 工作区和历史" onClick={() => void load()} disabled={loading || Boolean(busy)} className="rounded-md p-1 text-fg-3 hover:bg-hover hover:text-fg disabled:opacity-50">
        {loading ? <LoaderCircle size={13} className="spin" /> : <RefreshCw size={12} />}
      </button>
    </div>

    {error && <div role="alert" className="rounded-lg bg-danger-soft px-2.5 py-2 text-[11.5px] text-danger"><strong className="block font-semibold">Git 操作失败</strong><span className="block break-words">{error}</span></div>}
    {notice && <p role="status" className="m-0 rounded-lg bg-sunken px-2.5 py-1.5 text-[11.5px] text-fg-2">{notice}</p>}
    {!workspace && loading && <p className="m-0 text-[11.5px] text-fg-3">正在读取工作区…</p>}
    {!workspace && !loading && !error && <p className="m-0 text-[11.5px] text-fg-3">没有可用的 Git 工作区。</p>}

    {workspace && <>
      <div className="rounded-xl bg-sunken p-2.5">
        <div className="flex items-center gap-1.5 text-[11.5px] text-fg-3"><GitBranch size={12} />当前分支 <strong className="min-w-0 truncate font-medium text-fg">{workspace.current || '未知'}</strong></div>
        <div className="mt-2 grid gap-1.5">
          <div className="flex gap-1.5">
            <select aria-label="选择要切换的分支" value="" onChange={(event) => { if (event.target.value) void runBranch(event.target.value, false); }} disabled={Boolean(busy) || !workspace.branches.length} className={`${field} flex-1`}>
              <option value="">切换到已有分支…</option>
              {workspace.branches.filter((branch) => branch !== workspace.current).map((branch) => <option key={branch} value={branch}>{branch}</option>)}
            </select>
            <span className="sr-only">分支切换会更新这个工作区的当前分支。</span>
          </div>
          <form onSubmit={(event) => { event.preventDefault(); void runBranch(branchName, true); }} className="flex gap-1.5">
            <input aria-label="新分支名称" value={branchName} onChange={(event) => setBranchName(event.target.value)} placeholder="新分支名称" className={`${field} flex-1`} />
            <button className={action} disabled={!branchName.trim() || Boolean(busy)}><GitBranch size={12} />新建并切换</button>
          </form>
        </div>
      </div>

      <div className="grid gap-2 rounded-xl bg-sunken p-2.5">
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11.5px] font-medium text-fg-2">工作区改动</span>
          <label className="flex shrink-0 items-center gap-1.5 text-[10.5px] text-fg-3"><input type="checkbox" checked={allSelected} disabled={!paths.length || Boolean(busy)} onChange={(event) => setSelected(event.target.checked ? paths : [])} />全选</label>
        </div>
        {!workspace.status.length
          ? <p className="m-0 text-[11px] text-fg-3">工作区干净，没有待提交的文件。</p>
          : <ul className="m-0 grid max-h-36 list-none gap-0.5 overflow-auto p-0">
            {workspace.status.map(({ path, code }) => <li key={path} className="flex min-w-0 items-center gap-1.5 rounded-md px-1 py-0.5 hover:bg-hover">
              <input type="checkbox" aria-label={`选择 ${path}`} checked={selected.includes(path)} disabled={Boolean(busy)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, path] : current.filter((item) => item !== path))} />
              <code className="w-7 shrink-0 text-center font-mono text-[10px] text-fg-3">{code}</code>
              <span className="min-w-0 truncate text-[11px] text-fg-2" title={path}>{path}</span>
            </li>)}
          </ul>}
        <p className="m-0 text-[10.5px] text-fg-3">文件选择用于提交；推送会发布当前分支上已有的本地提交。</p>
        <form onSubmit={(event) => void commit(event)} className="grid gap-1.5">
          <input aria-label="提交说明" value={message} onChange={(event) => setMessage(event.target.value)} placeholder="提交说明" className={field} />
          <div className="flex gap-1.5">
            <button className={`${action} flex-1`} disabled={!message.trim() || !selected.length || Boolean(busy)}><GitCommitHorizontal size={12} />{busy === 'commit' ? '提交中…' : `提交 ${selectedLabel}`}</button>
            <button type="button" onClick={() => void commit(undefined, true)} className={`${action} flex-1`} disabled={!message.trim() || !selected.length || Boolean(busy)}><GitPullRequest size={12} />提交并推送</button>
            <button type="button" onClick={() => void push()} className={`${action} flex-1`} disabled={Boolean(busy)}><Upload size={12} />{busy === 'push' ? '推送中…' : '仅推送'}</button>
          </div>
        </form>
      </div>
    </>}

    <div>
      <h4 className="m-0 mb-1.5 flex items-center gap-1.5 text-[11.5px] font-semibold text-fg-2"><GitCommitHorizontal size={12} />提交历史（最近最多 200 条）</h4>
      {history?.commits.length
        ? <>
          <pre aria-label="提交历史拓扑" className="m-0 max-h-44 overflow-auto rounded-lg bg-sunken px-2 py-1.5 whitespace-pre font-mono text-[10px] leading-[1.45] text-brand">{history.graph.join('\n')}</pre>
          <ol className="m-0 mt-1 grid max-h-44 list-none gap-0 overflow-auto p-0">
          {history.commits.map((commit, index) => <li key={`${commit.hash}-${index}`} className="min-w-0 border-l border-line pl-2 py-1">
            <div className="min-w-0">
              <p className="m-0 truncate text-[11px] font-medium text-fg" title={commit.subject}>{commit.subject}</p>
              <p className="m-0 mt-0.5 truncate font-mono text-[9.5px] text-fg-3" title={commit.hash}>{commit.hash.slice(0, 10)}{commit.parents.length ? ` ← ${commit.parents.map((hash) => hash.slice(0, 7)).join(', ')}` : ' · 根提交'}</p>
              <p className="m-0 truncate text-[10px] text-fg-3">{commit.author}{commit.date ? ` · ${new Date(commit.date).toLocaleString()}` : ''}</p>
            </div>
          </li>)}
          </ol>
        </>
        : <p className="m-0 text-[11px] text-fg-3">{history ? '还没有提交历史。' : loading ? '正在读取提交历史…' : '提交历史暂不可用。'}</p>}
    </div>
  </section>;
}
