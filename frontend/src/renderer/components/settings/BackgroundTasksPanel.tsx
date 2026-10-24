import { useEffect, useState, type FormEvent } from 'react';
import { ArrowDown, ArrowUp, Play, Plus, Trash2 } from 'lucide-react';
import { api } from '../../services/api';

type IdleTask = { id: string; prompt: string; workspace: string; position: number; status: string };
type MailRule = { sender: string; subject: string; keyword: string; template: string };
type MailConfig = { enabled: boolean; server: string; username: string; interval_seconds: number; rules: MailRule[] };

export default function BackgroundTasksPanel({ apiBaseUrl }: { apiBaseUrl: string }) {
  const [tasks, setTasks] = useState<IdleTask[]>([]);
  const [mail, setMail] = useState<MailConfig>({ enabled: false, server: '', username: '', interval_seconds: 300, rules: [] });
  const [password, setPassword] = useState('');
  const [prompt, setPrompt] = useState('');
  const [workspace, setWorkspace] = useState('');
  const [error, setError] = useState('');
  const reload = async () => setTasks((await api<{ tasks: IdleTask[] }>(apiBaseUrl, '/api/idle-tasks')).tasks);
  useEffect(() => { void Promise.all([
    api<{ tasks: IdleTask[] }>(apiBaseUrl, '/api/idle-tasks'), api<MailConfig>(apiBaseUrl, '/api/mail-trigger'),
  ]).then(([queue, config]) => { setTasks(queue.tasks); setMail(config); }).catch((cause) => setError(String(cause))); }, [apiBaseUrl]);
  const addTask = async (event: FormEvent) => {
    event.preventDefault();
    try { await api(apiBaseUrl, '/api/idle-tasks', { method: 'POST', json: { prompt, workspace } }); setPrompt(''); await reload(); }
    catch (cause) { setError(String(cause)); }
  };
  const reorder = async (index: number, delta: number) => {
    const next = [...tasks]; const target = index + delta;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    try { setTasks((await api<{ tasks: IdleTask[] }>(apiBaseUrl, '/api/idle-tasks/order', { method: 'PUT', json: { ids: next.map((task) => task.id) } })).tasks); }
    catch (cause) { setError(String(cause)); }
  };
  const addRule = () => setMail((current) => ({ ...current, rules: [...current.rules, { sender: '', subject: '', keyword: '', template: '请处理这封邮件：{subject}\n发件人：{sender}\n摘要：{body_summary}' }] }));
  const saveMail = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setMail(await api<MailConfig>(apiBaseUrl, '/api/mail-trigger', { method: 'PUT', json: { ...mail, password: password || undefined } }));
      setPassword(''); setError('');
    } catch (cause) { setError(String(cause)); }
  };
  return <section className="grid max-w-[900px] gap-6" aria-label="后台任务设置">
    {error && <p role="alert" className="m-0 text-[12px] text-danger">{error}</p>}
    <div className="grid gap-3 rounded-xl border border-line p-4">
      <div><h3 className="m-0 text-[14px] font-medium">闲时任务队列</h3><p className="m-0 mt-1 text-[12px] text-fg-3">默认在 01:00–07:00 或电脑无输入 15 分钟后执行。可调整顺序、立即运行或取消。</p></div>
      <form onSubmit={(event) => void addTask(event)} className="flex flex-wrap gap-2">
        <input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="任务提示" className="h-8 min-w-[220px] flex-1 rounded-md border border-line bg-surface px-2 text-[12px]" />
        <input value={workspace} onChange={(event) => setWorkspace(event.target.value)} placeholder="工作区路径（可选）" className="h-8 min-w-[180px] rounded-md border border-line bg-surface px-2 text-[12px]" />
        <button className="btn primary" disabled={!prompt.trim()}><Plus size={14} />加入队列</button>
      </form>
      <div className="grid gap-1">{tasks.map((task, index) => <div key={task.id} className="flex items-center gap-2 rounded-lg bg-sunken px-2 py-1.5 text-[12px]">
        <span className="min-w-0 flex-1 truncate">{task.prompt}</span><span className="text-fg-3">{task.status}</span>
        <button aria-label="上移" onClick={() => void reorder(index, -1)}><ArrowUp size={14} /></button><button aria-label="下移" onClick={() => void reorder(index, 1)}><ArrowDown size={14} /></button>
        <button aria-label="立即运行" onClick={() => void api(apiBaseUrl, `/api/idle-tasks/${encodeURIComponent(task.id)}/run-now`, { method: 'POST' })}><Play size={14} /></button>
        <button aria-label="取消任务" onClick={() => void api(apiBaseUrl, `/api/idle-tasks/${encodeURIComponent(task.id)}`, { method: 'DELETE' }).then(reload)}><Trash2 size={14} /></button>
      </div>)}</div>
    </div>
    <form onSubmit={(event) => void saveMail(event)} className="grid gap-3 rounded-xl border border-line p-4">
      <div><h3 className="m-0 text-[14px] font-medium">IMAP 邮件触发</h3><p className="m-0 mt-1 text-[12px] text-fg-3">授权码存入系统密钥库；Atlas 只把匹配邮件的主题、发件人和摘要填入任务模板。</p></div>
      <label className="flex items-center gap-2 text-[12px]"><input type="checkbox" checked={mail.enabled} onChange={(event) => setMail({ ...mail, enabled: event.target.checked })} />启用轮询</label>
      <div className="grid gap-2 sm:grid-cols-2">
        <input value={mail.server} onChange={(event) => setMail({ ...mail, server: event.target.value })} placeholder="IMAP 服务器，例如 imap.example.com" className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]" />
        <input value={mail.username} onChange={(event) => setMail({ ...mail, username: event.target.value })} placeholder="账号" className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]" />
        <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} placeholder="授权码（留空保持已保存值）" className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]" />
        <input type="number" min={30} max={86400} value={mail.interval_seconds} onChange={(event) => setMail({ ...mail, interval_seconds: Number(event.target.value) })} aria-label="轮询间隔秒" className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]" />
      </div>
      {mail.rules.map((rule, index) => <div key={index} className="grid gap-2 rounded-lg bg-sunken p-2 sm:grid-cols-2">
        {(['sender', 'subject', 'keyword', 'template'] as const).map((field) => <input key={field} value={rule[field]} onChange={(event) => setMail({ ...mail, rules: mail.rules.map((item, i) => i === index ? { ...item, [field]: event.target.value } : item) })} placeholder={{ sender: '发件人包含', subject: '主题包含', keyword: '正文或主题关键字', template: '任务模板：{subject} {sender} {body_summary}' }[field]} className="h-8 rounded-md border border-line bg-surface px-2 text-[12px]" />)}
      </div>)}
      <div className="flex gap-2"><button type="button" className="btn ghost" onClick={addRule}><Plus size={14} />添加规则</button><button className="btn primary">保存 IMAP 设置</button></div>
    </form>
  </section>;
}
