import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { CheckCircle2, LoaderCircle, MessageSquare, Plus, Unplug } from 'lucide-react';
import { Button } from '../../ui/Button';

interface LinearTeam { id: string; name: string }
interface LinearViewer { id: string; name: string; email: string }
interface LinearStatus {
  configured: boolean;
  connected: boolean;
  viewer: LinearViewer | null;
  teams: LinearTeam[];
  error: string | null;
}
interface CreatedIssue { id: string; title: string }

const EMPTY_STATUS: LinearStatus = {
  configured: false, connected: false, viewer: null, teams: [], error: null,
};

async function request<T>(apiBaseUrl: string, path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`${apiBaseUrl.replace(/\/+$/, '')}${path}`, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let value: unknown;
  try { value = text ? JSON.parse(text) as unknown : null; } catch { value = text; }
  if (!response.ok) {
    const detail = value && typeof value === 'object' && 'detail' in value ? String(value.detail) : '';
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return value as T;
}

const inputClass = 'w-full rounded-lg border border-line bg-surface px-3 py-2 text-[13px] text-fg outline-none focus:border-brand';

/** Explicit-action Linear personal-key setup, issue creation, and comment posting. */
export default function LinearIntegrationPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [status, setStatus] = useState<LinearStatus>(EMPTY_STATUS);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [teamId, setTeamId] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [commentIssueId, setCommentIssueId] = useState('');
  const [commentBody, setCommentBody] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const next = await request<LinearStatus>(apiBaseUrl, '/api/integrations/linear/status');
      setStatus(next);
      setTeamId((current) => next.teams.some((team) => team.id === current) ? current : next.teams[0]?.id ?? '');
      if (next.error) setError(next.error);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl]);

  useEffect(() => { void reload(); }, [reload]);

  const connect = async (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim()) { setError('先粘贴 Linear personal API key。'); return; }
    setBusy('credential'); setError(''); setNotice('');
    try {
      const next = await request<LinearStatus>(apiBaseUrl, '/api/integrations/linear/credential', 'PUT', { api_key: apiKey.trim() });
      setStatus(next);
      setTeamId(next.teams[0]?.id ?? '');
      setApiKey('');
      setNotice('Linear 已验证，API key 已保存在系统凭据库。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const disconnect = async () => {
    setBusy('credential'); setError(''); setNotice('');
    try {
      await request<{ ok: boolean }>(apiBaseUrl, '/api/integrations/linear/credential', 'DELETE');
      setStatus(EMPTY_STATUS); setTeamId('');
      setNotice('Linear API key 已从系统凭据库清除。');
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const createIssue = async (event: FormEvent) => {
    event.preventDefault();
    if (!title.trim() || !teamId) return;
    setBusy('issue'); setError(''); setNotice('');
    try {
      const result = await request<CreatedIssue>(apiBaseUrl, '/api/integrations/linear/issues', 'POST', {
        title: title.trim(), description: description.trim(), team_id: teamId,
      });
      setCommentIssueId(result.id); setTitle(''); setDescription('');
      setNotice(`Issue 已创建：${result.title}（${result.id}）`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  const addComment = async (event: FormEvent) => {
    event.preventDefault();
    if (!commentIssueId.trim() || !commentBody.trim()) return;
    setBusy('comment'); setError(''); setNotice('');
    try {
      await request(apiBaseUrl, `/api/integrations/linear/issues/${encodeURIComponent(commentIssueId.trim())}/comments`, 'POST', { body: commentBody.trim() });
      setCommentBody('');
      setNotice(`评论已添加到 ${commentIssueId.trim()}。`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy('');
    }
  };

  return <div className="grid max-w-[760px] gap-4 text-[13px] text-fg-2" aria-label="Linear 集成">
    <section className="grid gap-3 rounded-xl border border-line p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="m-0 text-[14px] font-medium text-heading">Linear 连接</h3>
          <p className="mb-0 mt-1 text-[12px] leading-relaxed text-fg-3">使用个人 API key 读取账号与团队，并按需创建 issue、添加评论。密钥只保存在本机系统凭据库。</p>
        </div>
        {status.connected && <CheckCircle2 size={17} className="shrink-0 text-ok" aria-label="已连接" />}
      </div>

      <form className="grid gap-2 sm:grid-cols-[1fr_auto] sm:items-end" onSubmit={(event) => void connect(event)}>
        <label className="grid gap-1 text-[12px] text-fg-3">
          Personal API key
          <input type="password" autoComplete="new-password" value={apiKey} onChange={(event) => setApiKey(event.target.value)} className={`${inputClass} font-mono`} placeholder={status.configured ? '已保存；输入新 key 可替换' : '粘贴 Linear API key'} />
        </label>
        <Button type="submit" variant="secondary" disabled={busy === 'credential' || !apiKey.trim()}>
          {busy === 'credential' ? <LoaderCircle className="spin" /> : null}{status.configured ? '验证并替换' : '验证并保存'}
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-2 text-[12px] text-fg-3" role="status">
        {loading ? '正在读取 Linear 状态…' : status.connected
          ? `已连接：${status.viewer?.name || status.viewer?.email || 'Linear 用户'} · ${status.teams.length} 个可访问团队`
          : status.configured ? '系统凭据库中有 key，但当前无法验证连接。' : '尚未连接。'}
        {status.configured && <Button type="button" variant="ghost" size="sm" disabled={busy === 'credential'} onClick={() => void disconnect()}><Unplug size={13} />断开并清除</Button>}
        {status.configured && !status.connected && <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={() => void reload()}><LoaderCircle size={13} />重新检查</Button>}
      </div>
    </section>

    {status.connected && <>
      <form className="grid gap-3 rounded-xl border border-line p-4" onSubmit={(event) => void createIssue(event)}>
        <div><h3 className="m-0 text-[14px] font-medium text-heading">创建 issue</h3><p className="mb-0 mt-1 text-[12px] text-fg-3">提交会立即在所选 Linear 团队创建 issue。</p></div>
        <label className="grid gap-1 text-[12px] text-fg-3">团队
          <select required className={inputClass} value={teamId} onChange={(event) => setTeamId(event.target.value)}>
            {status.teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-[12px] text-fg-3">标题
          <input required maxLength={255} className={inputClass} value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-3">描述（Markdown）
          <textarea maxLength={30000} rows={4} className={inputClass} value={description} onChange={(event) => setDescription(event.target.value)} />
        </label>
        <div className="flex justify-end"><Button type="submit" variant="primary" disabled={busy === 'issue' || !teamId || !title.trim()}>{busy === 'issue' ? <LoaderCircle className="spin" /> : <Plus size={14} />}创建 issue</Button></div>
      </form>

      <form className="grid gap-3 rounded-xl border border-line p-4" onSubmit={(event) => void addComment(event)}>
        <div><h3 className="m-0 flex items-center gap-2 text-[14px] font-medium text-heading"><MessageSquare size={15} />添加 issue 评论</h3><p className="mb-0 mt-1 text-[12px] text-fg-3">填写 Linear issue UUID 或短 ID，例如 ABC-123；点击后立即提交评论。</p></div>
        <label className="grid gap-1 text-[12px] text-fg-3">Issue ID
          <input required className={`${inputClass} font-mono`} value={commentIssueId} onChange={(event) => setCommentIssueId(event.target.value)} placeholder="ABC-123" />
        </label>
        <label className="grid gap-1 text-[12px] text-fg-3">评论
          <textarea required maxLength={20000} rows={3} className={inputClass} value={commentBody} onChange={(event) => setCommentBody(event.target.value)} />
        </label>
        <div className="flex justify-end"><Button type="submit" variant="secondary" disabled={busy === 'comment' || !commentIssueId.trim() || !commentBody.trim()}>{busy === 'comment' ? <LoaderCircle className="spin" /> : <MessageSquare size={14} />}添加评论</Button></div>
      </form>
    </>}

    {error && <p className="m-0 rounded-lg bg-danger-soft px-3 py-2 text-danger" role="alert">{error}</p>}
    {notice && <p className="m-0 rounded-lg bg-sunken px-3 py-2 text-fg-3" role="status">{notice}</p>}
  </div>;
}
